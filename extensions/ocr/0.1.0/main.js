// Formal mock plugin: this never accesses real hardware or performs OCR.
const DEVICE_ID = 'mock-ocr-01';
export async function recognize(input) {
  return {
    schemaVersion: 1,
    pluginKind: 'ocr',
    mode: 'mock',
    deviceId: 'mock-ocr-01',
    data: {
      text: 'FOUNDRY MOCK TEXT',
      language: 'en',
      blocks: [
        {
          text: 'FOUNDRY MOCK TEXT',
          confidence: 1,
          boundingBox: {
            x: 0,
            y: 0,
            width: 1,
            height: 1,
          },
        },
      ],
    },
  };
}
