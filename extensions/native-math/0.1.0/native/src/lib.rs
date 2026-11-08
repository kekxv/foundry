/// Stable platform C ABI. JS rejects sums outside the i32 range.
#[unsafe(no_mangle)]
pub extern "C" fn foundry_add(a: i32, b: i32) -> i32 {
    a.wrapping_add(b)
}
#[unsafe(no_mangle)]
pub extern "C" fn foundry_hypot(a: f64, b: f64) -> f64 {
    a.hypot(b)
}
