// Formal mock plugin: this never accesses real hardware or performs OCR.
const DEVICE_ID = 'mock-serial-port-01';
function checkDevice(input) {
  if (input.deviceId !== undefined && input.deviceId !== DEVICE_ID)
    throw new Error('DEVICE_NOT_FOUND: unknown device identifier');
}

export async function devices() {
  return {
    schemaVersion: 1,
    pluginKind: 'serial',
    mode: 'mock',
    devices: [
      {
        id: 'mock-serial-port-01',
        name: 'Mock Serial Port',
        transport: 'mock',
        status: 'ready',
      },
    ],
  };
}

export async function exchange(input) {
  checkDevice(input);
  return {
    schemaVersion: 1,
    pluginKind: 'serial',
    mode: 'mock',
    deviceId: DEVICE_ID,
    data: {
      request: input.message,
      response: input.message === 'PING' ? 'PONG' : 'ECHO:' + input.message,
      encoding: 'utf8',
    },
  };
}
