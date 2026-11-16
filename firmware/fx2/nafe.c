// Ref: NAFE71388 Universal ±25 V 8-Input High Speed AFE Rev. 2
// Accession: G00131

#include <stddef.h>
#include <fx2i2c.h>
#include <fx2lib.h>
#include <fx2delay.h>
#include "glasgow.h"

#define BSWAP16(x) ((((uint16_t)x)>>8)|(((uint16_t)x)<<8))

typedef __xdata struct {
  uint8_t op;
  uint16_t cmd;
  __xdata void *data;
} nafe_sequence;

#define NAFE_COMMAND(addr)            {0x00,     BSWAP16((addr)<<1), NULL}
#define NAFE_WR_DATA(addr, len, data) {0x00|len, BSWAP16((addr)<<1), &data}
#define NAFE_RD_DATA(addr, len, data) {0x80|len, BSWAP16((addr)<<1), &data}

static const __xdata uint8_t mcu_cmd_nafe[2] = { MCU_CMD_NAFE, MCU_CMD_MEAS };

bool nafe_run(nafe_sequence *seq)
{
  while (1) {
    uint8_t op = seq->op;
    if (!i2c_start((I2C_ADDR_STM32_APP_REVD<<1)|0))
      goto fail;
    if (!i2c_write(&mcu_cmd_nafe[op >> 7], 1))
      goto fail;
    if (!i2c_write(&seq->cmd, sizeof(seq->cmd)))
      goto fail;
    uint8_t len = op & 0x0F;
    if (op & 0x80) {
      if (!i2c_start((I2C_ADDR_STM32_APP_REVD<<1)|1))
        goto fail;
      if (!i2c_read(seq->data, len))
        return false;
      // Done!
      return true;
    } else {
      if (!i2c_write(seq->data, len))
        goto fail;
    }
    seq++;
  }

fail:
  i2c_stop();
  return false;
}

static __xdata uint16_t nafe_sys_config0 =
  BSWAP16(0b1'0'0'0'00'11'0'0'0'1'0'0'0'0);  // SYS_CONFIG0={DRDY_PWDT,XTAL,DRDY_PIN_EDGE}
static __xdata uint16_t nafe_ch_config0[3] = { // CH_CONFIG0={HV_AI[PN]=(dynamic),...}
  BSWAP16(0b0000'0000'010'1'000'0),          // ...={CH_GAIN=0.8x,HV_SEL=1,TCC_OFF=0}
  BSWAP16(0b0000'0000'001'1'000'0),          // ...={CH_GAIN=0.4x,HV_SEL=1,TCC_OFF=0}
  BSWAP16(0b0000'0000'000'1'000'0),          // ...={CH_GAIN=0.2x,HV_SEL=1,TCC_OFF=0}
};
static __xdata uint16_t nafe_ch_config1[3] = { // CH_CONFIG1={ADC_DATA_RATE=(dynamic),...}
  BSWAP16(0b0000'0000'01011'100),            // ...={CH_CAL=0,CH_THRS=0,ADC_SINC=4)
  BSWAP16(0b0001'0000'01011'100),            // ...={CH_CAL=1,CH_THRS=0,ADC_SINC=4)
  BSWAP16(0b0010'0000'01011'100),            // ...={CH_CAL=2,CH_THRS=0,ADC_SINC=4)
};
static __xdata uint16_t nafe_ch_config2 =
  BSWAP16(0b000000'0'1'0'0000000);           // CH_CONFIG2={ADC_FILTER_RESET}
static __xdata uint16_t nafe_ch_config4 =
  BSWAP16(0b111);                            // CH_CONFIG4={MCH_EN=0,1,2}
static __xdata uint8_t nafe_ch_data[9];

static nafe_sequence nafe_seq_single[] = {
  NAFE_COMMAND(0x0015),                         // CMD_CLEAR_REG
  NAFE_WR_DATA(0x0030, 2, nafe_sys_config0),    // SYS_CONFIG0
  NAFE_COMMAND(0x0002),                         // CMD_CH2 (0.2x)
  NAFE_WR_DATA(0x0020, 2, nafe_ch_config0[2]),  // CH_CONFIG0
  NAFE_WR_DATA(0x0021, 2, nafe_ch_config1[2]),  // CH_CONFIG1
  NAFE_WR_DATA(0x0022, 2, nafe_ch_config2),     // CH_CONFIG2
  NAFE_COMMAND(0x0001),                         // CMD_CH1 (0.4x)
  NAFE_WR_DATA(0x0020, 2, nafe_ch_config0[1]),  // CH_CONFIG0
  NAFE_WR_DATA(0x0021, 2, nafe_ch_config1[1]),  // CH_CONFIG1
  NAFE_WR_DATA(0x0022, 2, nafe_ch_config2),     // CH_CONFIG2
  NAFE_COMMAND(0x0000),                         // CMD_CH0 (0.8x)
  NAFE_WR_DATA(0x0020, 2, nafe_ch_config0[0]),  // CH_CONFIG0
  NAFE_WR_DATA(0x0021, 2, nafe_ch_config1[0]),  // CH_CONFIG1
  NAFE_WR_DATA(0x0022, 2, nafe_ch_config2),     // CH_CONFIG2
  NAFE_WR_DATA(0x0024, 2, nafe_ch_config4),     // CH_CONFIG4
  NAFE_RD_DATA(0x2002, 9, nafe_ch_data[0]),     // CMD_MM
};

static __bit nafe_convert_uvolts(int ch_gain)
{
  // Implements `uvolts = code * (10 / 2**24) / gain * 1000000` in a way that's compact on a 8051
  // and minimizes rounding error as much as possible.
  int32_t value = (int32_t)bswap32(*(__xdata int32_t *)&nafe_ch_data[ch_gain * 3]) >> 8;
  __bit out_of_range = value < -0x666666 || value > 0x666666;
  for (int i = 0; i < 3 - ch_gain; i++)
    value >>= 1;
  for (int i = 0; i < 4; i++)
    value = (value * 25) >> 4;
  mgmt_rsp.nafe_single_data.value = value;
  mgmt_rsp.nafe_single_data.gain = 2 - ch_gain;
  return out_of_range;
}

enum mgmt_result nafe_mgmt_single()
{
  // Configure the channels. (The straight line version results in smaller code.)
  uint8_t hv_aipn   = (mgmt_req.nafe_single.in_pos << 4) | (mgmt_req.nafe_single.in_neg << 0);
  uint8_t rate_filt = mgmt_req.nafe_single.rate_filt;
  *(((__xdata uint8_t *)&nafe_ch_config0[0])+0) = hv_aipn;
  *(((__xdata uint8_t *)&nafe_ch_config1[0])+1) = rate_filt;
  *(((__xdata uint8_t *)&nafe_ch_config0[1])+0) = hv_aipn;
  *(((__xdata uint8_t *)&nafe_ch_config1[1])+1) = rate_filt;
  *(((__xdata uint8_t *)&nafe_ch_config0[2])+0) = hv_aipn;
  *(((__xdata uint8_t *)&nafe_ch_config1[2])+1) = rate_filt;

  // Run the command sequence. This captures three values, with 0.8x, 0.4x, and 0.2x PGA gain.
  if (!nafe_run(nafe_seq_single))
    return RES_ERROR;

  // Convert the result with automatic PGA gain selection.
  if (nafe_convert_uvolts(0))
    if (nafe_convert_uvolts(1))
      nafe_convert_uvolts(2);
  return RES_ACK;
}
