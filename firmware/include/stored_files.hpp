#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "protocols.hpp"

struct StoredFileView
{
  const uint8_t *data = nullptr;
  size_t size = 0;
  uint32_t sample_rate = 0;
  uint16_t channels = 0;
};

class StoredFiles
{
public:
  void init();
  void resetSession();

  bool handleStart(uint32_t seq, const stackchan_websocket_v1_StoredFileStart &start);
  bool handleData(uint32_t seq, const uint8_t *data, size_t data_len);
  bool handleEnd(uint32_t seq);

  bool getActivePcmFile(const char *fileId, StoredFileView &view);

private:
  static constexpr size_t kMaxStoredFiles = 4;
  static constexpr size_t kMaxStoredFileBytes = 256 * 1024;

  struct PersistedSlot
  {
    bool used = false;
    char file_id[64] = "";
    char content_type[64] = "";
    uint32_t sample_rate = 0;
    uint32_t channels = 0;
    uint32_t size = 0;
  };

  struct TransferState
  {
    bool active = false;
    uint32_t next_seq = 0;
    int slot_index = -1;
    uint32_t received_bytes = 0;
    uint32_t chunk_count = 0;
    PersistedSlot slot{};
    std::vector<uint8_t> payload;
  };

  bool storage_ready_ = false;
  std::array<PersistedSlot, kMaxStoredFiles> slots_{};
  std::array<bool, kMaxStoredFiles> session_active_{};
  int cached_slot_index_ = -1;
  std::vector<uint8_t> cached_payload_;
  TransferState transfer_;

  bool mountSpiffs();
  bool loadIndex();
  bool persistIndex();
  bool persistSlotPayload(int slotIndex, const std::vector<uint8_t> &payload);
  bool loadSlotPayload(int slotIndex, std::vector<uint8_t> &payload);
  int findSlotById(const char *fileId) const;
  int selectSlotForId(const char *fileId);
  void resetTransfer();
  bool activateSlot(int slotIndex, const std::vector<uint8_t> &payload);
  static const char *payloadPathForSlot(int slotIndex);
  static const char *indexPath();
};
