#include "../include/metadata.hpp"

#include <M5Unified.h>

#include <cstdio>

#include "config.h"

FirmwareMetadataState g_firmware_metadata;
ServerMetadataState g_server_metadata;

namespace
{
stackchan_websocket_v1_DeviceType detectDeviceType()
{
#if defined(ARDUINO_ATOM_ECHOS3R)
  return stackchan_websocket_v1_DeviceType_DEVICE_TYPE_M5ATOM_ECHOS3R;
#elif defined(ARDUINO_M5STACK_ATOMS3R)
  return stackchan_websocket_v1_DeviceType_DEVICE_TYPE_M5ATOM_S3R;
#elif defined(ARDUINO_M5STACK_CORES3)
  return stackchan_websocket_v1_DeviceType_DEVICE_TYPE_M5STACK_CORES3;
#else
  return stackchan_websocket_v1_DeviceType_DEVICE_TYPE_UNSPECIFIED;
#endif
}

bool detectHasLed()
{
#if defined(ARDUINO_ATOM_ECHOS3R) || defined(ARDUINO_M5STACK_ATOMS3R)
  return true;
#else
  return false;
#endif
}

stackchan_websocket_v1_ServoType detectServoType()
{
#if USE_STACKCHAN_BSP
  return stackchan_websocket_v1_ServoType_SERVO_TYPE_SCS0009;
#elif defined(USE_SERVO_SG90)
  return stackchan_websocket_v1_ServoType_SERVO_TYPE_SG90;
#elif defined(USE_SERVO_SCS0009)
  return stackchan_websocket_v1_ServoType_SERVO_TYPE_SCS0009;
#else
  return stackchan_websocket_v1_ServoType_SERVO_TYPE_NONE;
#endif
}
} // namespace

void initializeFirmwareMetadata()
{
  g_firmware_metadata.device_type = detectDeviceType();
  g_firmware_metadata.display_width = static_cast<uint32_t>(M5.Display.width());
  g_firmware_metadata.display_height = static_cast<uint32_t>(M5.Display.height());
  g_firmware_metadata.has_device_wake_word = true;
  g_firmware_metadata.has_led = detectHasLed();
  g_firmware_metadata.servo_type = detectServoType();
  g_firmware_metadata.supports_audio_duplex = false;
  snprintf(
      g_firmware_metadata.firmware_version,
      sizeof(g_firmware_metadata.firmware_version),
      "%s",
      STACKCHAN_FIRMWARE_VERSION);
}

void resetServerMetadata()
{
  g_server_metadata = ServerMetadataState{};
}

bool shouldUseDeviceWakeWord()
{
  return g_server_metadata.available && !g_server_metadata.has_server_wake_word;
}

void setFirmwareMetadataMessage(
    stackchan_websocket_v1_WebSocketMessage &message,
    uint32_t seq)
{
  message = stackchan_websocket_v1_WebSocketMessage_init_zero;
  message.kind = stackchan_websocket_v1_MessageKind_MESSAGE_KIND_FIRMWARE_METADATA;
  message.message_type = stackchan_websocket_v1_MessageType_MESSAGE_TYPE_DATA;
  message.seq = seq;
  message.which_body = stackchan_websocket_v1_WebSocketMessage_firmware_metadata_tag;
  message.body.firmware_metadata.device_type = g_firmware_metadata.device_type;
  message.body.firmware_metadata.display_width = g_firmware_metadata.display_width;
  message.body.firmware_metadata.display_height = g_firmware_metadata.display_height;
  message.body.firmware_metadata.has_device_wake_word = g_firmware_metadata.has_device_wake_word;
  message.body.firmware_metadata.has_led = g_firmware_metadata.has_led;
  message.body.firmware_metadata.servo_type = g_firmware_metadata.servo_type;
  message.body.firmware_metadata.supports_audio_duplex = g_firmware_metadata.supports_audio_duplex;
  snprintf(
      message.body.firmware_metadata.firmware_version,
      sizeof(message.body.firmware_metadata.firmware_version),
      "%s",
      g_firmware_metadata.firmware_version);
}

void applyServerMetadata(const stackchan_websocket_v1_ServerMetadata &metadata)
{
  g_server_metadata.available = true;
  g_server_metadata.has_server_wake_word = metadata.has_server_wake_word;
  snprintf(
      g_server_metadata.server_version,
      sizeof(g_server_metadata.server_version),
      "%s",
      metadata.server_version);
  log_i(
      "Server metadata wakeword=%u version=%s",
      static_cast<unsigned>(g_server_metadata.has_server_wake_word),
      g_server_metadata.server_version);
}
