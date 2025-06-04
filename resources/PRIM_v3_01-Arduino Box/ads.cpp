#include "ads.h"

// < Constructor >
double ADS1115::measure(int source)
{
  _source = source;
  if (_source == 0) {
    readADC = readADC_Differential_0_1();
  }
  else if (_source == 1) {
    readADC = readADC_Differential_2_3();
  }
  converted = ((_outputMax - _outputMin) / (_inputMax - _inputMin)) * (readADC - _inputMin) + _outputMin;
  return (converted);
}

void ADS1115::linearCal(int inputMin, int inputMax, double outputMin, double outputMax)
{
  _inputMin = inputMin;
  _inputMax = inputMax;
  _outputMin = outputMin;
  _outputMax = outputMax;
}

ADS1115::ADS1115() 
{
  m_bitShift = 0;
  m_gain = GAIN_TWOTHIRDS; /* +/- 6.144V range (limited to VDD +0.3V max!) */
  m_dataRate = RATE_ADS1115_860SPS;
}

bool ADS1115::begin(uint8_t i2c_addr, TwoWire *wire) {
  m_i2c_dev = new Adafruit_I2CDevice(i2c_addr, wire);
  return m_i2c_dev->begin();
}

void ADS1115::setGain(adsGain_t gain) { m_gain = gain; }
adsGain_t ADS1115::getGain() { return m_gain; }
void ADS1115::setDataRate(uint16_t rate) { m_dataRate = rate; }

void ADS1115::startADCReading(uint16_t mux, bool continuous) {
  uint16_t config =
      ADS1X15_REG_CONFIG_CQUE_1CONV |   // Set CQUE to any value other than
                                        // None so we can use it in RDY mode
      ADS1X15_REG_CONFIG_CLAT_NONLAT |  // Non-latching (default val)
      ADS1X15_REG_CONFIG_CPOL_ACTVLOW | // Alert/Rdy active low   (default val)
      ADS1X15_REG_CONFIG_CMODE_TRAD;    // Traditional comparator (default val)

  if (continuous) {
    config |= ADS1X15_REG_CONFIG_MODE_CONTIN;
  } else {
    config |= ADS1X15_REG_CONFIG_MODE_SINGLE;
  }
  config |= m_gain;       // Set PGA/voltage range
  config |= m_dataRate;   // Set data rate
  config |= mux;          // Set channels
  config |= ADS1X15_REG_CONFIG_OS_SINGLE; // Set 'start single-conversion' bit
  writeRegister(ADS1X15_REG_POINTER_CONFIG, config); // Write config register to the ADC
  writeRegister(ADS1X15_REG_POINTER_HITHRESH, 0x8000); // Set ALERT/RDY to RDY mode.
  writeRegister(ADS1X15_REG_POINTER_LOWTHRESH, 0x0000);
}

int16_t ADS1115::readADC_Differential_0_1() {
  startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_0_1, /*continuous=*/false);
  while (!conversionComplete());  // Wait for the conversion to complete
  return getLastConversionResults();  // Read the conversion results
}

int16_t ADS1115::readADC_Differential_2_3() {
  startADCReading(ADS1X15_REG_CONFIG_MUX_DIFF_2_3, /*continuous=*/false);
  while (!conversionComplete());  // Wait for the conversion to complete
  return getLastConversionResults();  // Read the conversion results
}

int16_t ADS1115::getLastConversionResults() {
  uint16_t res = readRegister(ADS1X15_REG_POINTER_CONVERT) >> m_bitShift; // Read the conversion results
  if (m_bitShift == 0) {
    return (int16_t)res;
  } else {
    if (res > 0x07FF) { // Shift 12-bit results right 4 bits for the ADS1015, making sure we keep the sign bit intact
      res |= 0xF000;  // negative number - extend the sign to 16th bit
    }
    return (int16_t)res;
  }
}

bool ADS1115::conversionComplete() {
  return (readRegister(ADS1X15_REG_POINTER_CONFIG) & 0x8000) != 0;
}

void ADS1115::writeRegister(uint8_t reg, uint16_t value) {
  buffer[0] = reg;
  buffer[1] = value >> 8;
  buffer[2] = value & 0xFF;
  m_i2c_dev->write(buffer, 3);
}

uint16_t ADS1115::readRegister(uint8_t reg) {
  buffer[0] = reg;
  m_i2c_dev->write(buffer, 1);
  m_i2c_dev->read(buffer, 2);
  return ((buffer[0] << 8) | buffer[1]);
}