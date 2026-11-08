use anyhow::{Result, ensure};
use std::{
    io::{Read, Write},
    process::{Command, Stdio},
    sync::mpsc,
    time::{Duration, Instant},
};
#[derive(Debug)]
pub struct ProcessResult {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}
const MAX_OUTPUT: usize = 1024 * 1024;
fn drain(
    mut stream: impl Read + Send + 'static,
    tx: mpsc::Sender<(bool, Result<Vec<u8>>)>,
    stderr: bool,
) {
    std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = (|| -> Result<Vec<u8>> {
            stream
                .by_ref()
                .take(MAX_OUTPUT as u64 + 1)
                .read_to_end(&mut bytes)?;
            ensure!(bytes.len() <= MAX_OUTPUT, "process output exceeded limit");
            Ok(bytes)
        })();
        let _ = tx.send((stderr, result));
    });
}
pub fn run_process(
    cmd: &mut Command,
    input: Option<Vec<u8>>,
    timeout: Duration,
    _new_group: bool,
) -> Result<ProcessResult> {
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // Do not permit loader search paths from the invoking environment to inject libraries.
    for name in [
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
    ] {
        cmd.env_remove(name);
    }
    #[cfg(unix)]
    if _new_group {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000 | 0x00000004); // CREATE_NO_WINDOW | CREATE_SUSPENDED
    }
    let mut child = cmd.spawn()?;
    #[cfg(unix)]
    let pid = child.id();
    #[cfg(windows)]
    let _job = match WindowsJob::attach(&child).and_then(|job| {
        WindowsJob::resume(&child)?;
        Ok(job)
    }) {
        Ok(job) => job,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    let stdin = child.stdin.take();
    let writer = std::thread::spawn(move || {
        if let (Some(mut stdin), Some(input)) = (stdin, input) {
            let _ = stdin.write_all(&input);
        }
    });
    let (tx, rx) = mpsc::channel();
    drain(child.stdout.take().unwrap(), tx.clone(), false);
    drain(child.stderr.take().unwrap(), tx, true);
    let start = Instant::now();
    let mut out = None;
    let mut err = None;
    let result = (|| -> Result<ProcessResult> {
        loop {
            ensure!(start.elapsed() < timeout, "native process timed out");
            while let Ok((stderr, data)) = rx.try_recv() {
                let data = data?;
                if stderr {
                    err = Some(data);
                } else {
                    out = Some(data);
                }
            }
            if let (Some(o), Some(e)) = (&out, &err) {
                ensure!(
                    o.len() + e.len() <= MAX_OUTPUT,
                    "combined output exceeded limit"
                );
                if let Some(status) = child.try_wait()? {
                    return Ok(ProcessResult {
                        exit_code: status.code().unwrap_or(-1),
                        stdout: String::from_utf8(o.clone())?,
                        stderr: String::from_utf8(e.clone())?,
                    });
                }
            }
            std::thread::sleep(Duration::from_millis(2));
        }
    })();
    // Kill descendants even when a process exited but left pipes or child processes alive.
    #[cfg(unix)]
    if _new_group {
        unsafe {
            libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
    if result.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    let _ = writer.join();
    result
}
#[cfg(windows)]
struct WindowsJob(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
impl WindowsJob {
    fn resume(child: &std::process::Child) -> Result<()> {
        use windows_sys::Win32::{
            Foundation::{CloseHandle, INVALID_HANDLE_VALUE},
            System::{Diagnostics::ToolHelp::*, Threading::*},
        };
        unsafe {
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
            ensure!(
                snapshot != INVALID_HANDLE_VALUE,
                "cannot enumerate suspended process threads"
            );
            let result = (|| -> Result<()> {
                let mut entry: THREADENTRY32 = std::mem::zeroed();
                entry.dwSize = std::mem::size_of_val(&entry) as u32;
                let mut more = Thread32First(snapshot, &mut entry);
                let mut resumed = false;
                while more != 0 {
                    if entry.th32OwnerProcessID == child.id() {
                        let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                        ensure!(!thread.is_null(), "cannot open suspended thread");
                        let previous = ResumeThread(thread);
                        CloseHandle(thread);
                        ensure!(previous != u32::MAX, "cannot resume process");
                        resumed = true;
                    }
                    more = Thread32Next(snapshot, &mut entry);
                }
                ensure!(resumed, "suspended process has no resumable thread");
                Ok(())
            })();
            CloseHandle(snapshot);
            result
        }
    }

    fn attach(child: &std::process::Child) -> Result<Self> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            ensure!(!job.is_null(), "CreateJobObject failed");
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                std::mem::size_of_val(&info) as u32,
            ) == 0
                || AssignProcessToJobObject(job, child.as_raw_handle()) == 0
            {
                CloseHandle(job);
                anyhow::bail!("cannot assign process job");
            }
            Ok(Self(job))
        }
    }
}
#[cfg(windows)]
impl Drop for WindowsJob {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}
