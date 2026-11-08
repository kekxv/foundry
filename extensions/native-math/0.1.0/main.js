export async function add({a, b}) {
  if (a + b < -2147483648 || a + b > 2147483647) {
    throw new RangeError('sum exceeds i32 range');
  }
  return {result: await host.library('math').call('add', [a, b])};
}
export async function hypot({a, b}) {
  return {result: await host.library('math').call('hypot', [a, b])};
}
