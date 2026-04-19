#pragma once

#include <cstdint>

#include "protocols.hpp"

struct FirmwareMetadataState
{
  stackchan_websocket_v1_DeviceType device_type = stackchan_websocket_v1_DeviceType_DEVICE_TYPE_UNSPECIFIED;
  uint32_t display_width = 0;
  uint32_t display_height = 0;
  bool has_device_wake_word = false;
  bool has_led = false;
  stackchan_websocket_v1_ServoType servo_type = stackchan_websocket_v1_ServoType_SERVO_TYPE_UNSPECIFIED;
  bool supports_audio_duplex = false;
  char firmware_version[64] = "";
};

struct ServerMetadataState
{
  bool available = false;
  bool has_server_wake_word = false;
  char server_version[64] = "";
};

extern FirmwareMetadataState g_firmware_metadata;
extern ServerMetadataState g_server_metadata;

void initializeFirmwareMetadata();
void resetServerMetadata();
bool shouldUseDeviceWakeWord();
void setFirmwareMetadataMessage(
    stackchan_websocket_v1_WebSocketMessage &message,
    uint32_t seq);
void applyServerMetadata(const stackchan_websocket_v1_ServerMetadata &metadata);
