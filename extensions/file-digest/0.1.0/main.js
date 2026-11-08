export async function digest({path}) {
  const result = await host.exec('digest', [path]);
  if (result.exitCode !== 0) throw new Error(result.stderr);
  return JSON.parse(result.stdout);
}
