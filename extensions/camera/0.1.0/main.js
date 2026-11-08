// Formal mock plugin: this never accesses real hardware or performs OCR.
const DEVICE_ID = 'mock-camera-01';
function checkDevice(input) {
  if (input.deviceId !== undefined && input.deviceId !== DEVICE_ID)
    throw new Error('DEVICE_NOT_FOUND: unknown device identifier');
}

export async function devices() {
  return {
    schemaVersion: 1,
    pluginKind: 'camera',
    mode: 'mock',
    devices: [
      {
        id: 'mock-camera-01',
        name: 'Mock Camera',
        transport: 'mock',
        status: 'ready',
      },
    ],
  };
}

export async function capture(input) {
  checkDevice(input);
  return {
    schemaVersion: 1,
    pluginKind: 'camera',
    mode: 'mock',
    deviceId: 'mock-camera-01',
    data: {
      image: {
        mimeType: 'image/png',
        base64:
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP4DwQACfsD/Wj6HMwAAAAASUVORK5CYII=',
        width: 1,
        height: 1,
      },
    },
  };
}
