// Formal mock plugin: this never accesses real hardware or performs OCR.
const DEVICE_ID = 'mock-id-card-reader-01';
function checkDevice(input) {
  if (input.deviceId !== undefined && input.deviceId !== DEVICE_ID)
    throw new Error('DEVICE_NOT_FOUND: unknown device identifier');
}

export async function devices() {
  return {
    schemaVersion: 1,
    pluginKind: 'id-card-reader',
    mode: 'mock',
    devices: [
      {
        id: 'mock-id-card-reader-01',
        name: 'Mock Identity Reader',
        transport: 'mock',
        status: 'ready',
      },
    ],
  };
}

export async function readCard(input) {
  checkDevice(input);
  return {
    schemaVersion: 1,
    pluginKind: 'id-card-reader',
    mode: 'mock',
    deviceId: 'mock-id-card-reader-01',
    data: {
      documentType: 'cn-resident-id',
      name: '模拟测试人员',
      gender: 'unknown',
      ethnicity: '测试民族',
      birthDate: '1990-01-01',
      address: '测试省测试市测试区示例路1号',
      idNumber: '000000199001010000',
      issuingAuthority: '模拟签发机关',
      validFrom: '2020-01-01',
      validTo: '2030-01-01',
      photo: null,
    },
  };
}
