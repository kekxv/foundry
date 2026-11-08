/** Stable JSON interface; runs in QuickJS without Node.js. */
export async function normalize({text}) {
  return {text: text.replace(/\r\n/g, '\n').trim()};
}
