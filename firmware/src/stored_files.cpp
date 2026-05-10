#include "stored_files.hpp"

#include <M5Unified.h>
#include <SPIFFS.h>

#include <cstdio>
#include <cstring>
#include <utility>

namespace
{
constexpr const char *kIndexFilePath = "/wsfiles.idx";
constexpr const char *kPayloadPaths[] = {
    "/wsfile0.bin",
    "/wsfile1.bin",
    "/wsfile2.bin",
    "/wsfile3.bin",
};
} // namespace

void StoredFiles::init()
{
  session_active_.fill(false);
  cached_slot_index_ = -1;
  cached_payload_.clear();
  resetTransfer();

  if (!mountSpiffs())
  {
    return;
  }

  log_i(
      "SPIFFS mounted total=%u used=%u",
      static_cast<unsigned>(SPIFFS.totalBytes()),
      static_cast<unsigned>(SPIFFS.usedBytes()));

  if (!loadIndex())
  {
    slots_ = {};
    persistIndex();
  }
}

void StoredFiles::resetSession()
{
  session_active_.fill(false);
  cached_slot_index_ = -1;
  cached_payload_.clear();
  resetTransfer();
}

bool StoredFiles::handleStart(uint32_t seq, const stackchan_websocket_v1_StoredFileStart &start)
{
  if (!mountSpiffs())
  {
    return false;
  }

  resetTransfer();

  if (start.file_id[0] == '\0')
  {
    log_w("Stored file start missing file_id");
    return false;
  }

  size_t total_size = static_cast<size_t>(start.total_size);
  if (total_size > kMaxStoredFileBytes)
  {
    log_w(
        "Stored file too large for SPIFFS-backed transfer id=%s size=%u limit=%u",
        start.file_id,
        static_cast<unsigned>(start.total_size),
        static_cast<unsigned>(kMaxStoredFileBytes));
    return false;
  }

  int slot_index = selectSlotForId(start.file_id);
  if (slot_index < 0)
  {
    log_w("No slot available for stored file id=%s", start.file_id);
    return false;
  }

  size_t reclaimable_bytes = slots_[slot_index].used ? slots_[slot_index].size : 0;
  size_t total_bytes = SPIFFS.totalBytes();
  size_t used_bytes = SPIFFS.usedBytes();
  size_t free_bytes = total_bytes > used_bytes ? total_bytes - used_bytes : 0;
  size_t available_bytes = free_bytes + reclaimable_bytes;
  if (total_bytes > 0 && total_size > available_bytes)
  {
    log_w(
        "Insufficient SPIFFS space for stored file id=%s requested=%u free=%u reclaimable=%u",
        start.file_id,
        static_cast<unsigned>(total_size),
        static_cast<unsigned>(free_bytes),
        static_cast<unsigned>(reclaimable_bytes));
    return false;
  }

  transfer_.active = true;
  transfer_.next_seq = seq + 1;
  transfer_.slot_index = slot_index;
  transfer_.slot = PersistedSlot{};
  transfer_.slot.used = true;
  snprintf(transfer_.slot.file_id, sizeof(transfer_.slot.file_id), "%s", start.file_id);
  snprintf(transfer_.slot.content_type, sizeof(transfer_.slot.content_type), "%s", start.content_type);
  transfer_.slot.sample_rate = start.sample_rate;
  transfer_.slot.channels = start.channels;
  transfer_.slot.size = static_cast<uint32_t>(total_size);
  transfer_.received_bytes = 0;
  transfer_.chunk_count = 0;
  transfer_.payload.clear();
  transfer_.payload.reserve(total_size);

  log_i(
      "Stored file start id=%s type=%s size=%u sample_rate=%u channels=%u slot=%d spiffs_free=%u",
      transfer_.slot.file_id,
      transfer_.slot.content_type,
      static_cast<unsigned>(transfer_.slot.size),
      static_cast<unsigned>(transfer_.slot.sample_rate),
      static_cast<unsigned>(transfer_.slot.channels),
      slot_index,
      static_cast<unsigned>(free_bytes));
  return true;
}

bool StoredFiles::handleData(uint32_t seq, const uint8_t *data, size_t data_len)
{
  if (!transfer_.active)
  {
    log_w("Stored file data without active transfer");
    return false;
  }

  if (seq != transfer_.next_seq)
  {
    log_w("Stored file seq gap got=%u expected=%u", static_cast<unsigned>(seq), static_cast<unsigned>(transfer_.next_seq));
    resetTransfer();
    return false;
  }
  transfer_.next_seq++;

  size_t next_size = transfer_.payload.size() + data_len;
  if (next_size > transfer_.slot.size || next_size > kMaxStoredFileBytes)
  {
    log_w("Stored file payload too large id=%s size=%u expected=%u",
          transfer_.slot.file_id,
          static_cast<unsigned>(next_size),
          static_cast<unsigned>(transfer_.slot.size));
    resetTransfer();
    return false;
  }

  transfer_.payload.insert(transfer_.payload.end(), data, data + data_len);
  transfer_.received_bytes += static_cast<uint32_t>(data_len);
  transfer_.chunk_count++;
  log_i(
      "Stored file chunk id=%s chunk=%u bytes=%u total=%u/%u",
      transfer_.slot.file_id,
      static_cast<unsigned>(transfer_.chunk_count),
      static_cast<unsigned>(data_len),
      static_cast<unsigned>(transfer_.received_bytes),
      static_cast<unsigned>(transfer_.slot.size));
  return true;
}

bool StoredFiles::handleEnd(uint32_t seq)
{
  if (!transfer_.active)
  {
    log_w("Stored file end without active transfer");
    return false;
  }

  if (seq != transfer_.next_seq)
  {
    log_w("Stored file end seq gap got=%u expected=%u", static_cast<unsigned>(seq), static_cast<unsigned>(transfer_.next_seq));
    resetTransfer();
    return false;
  }

  if (transfer_.payload.size() != transfer_.slot.size)
  {
    log_w("Stored file size mismatch id=%s actual=%u expected=%u",
          transfer_.slot.file_id,
          static_cast<unsigned>(transfer_.payload.size()),
          static_cast<unsigned>(transfer_.slot.size));
    resetTransfer();
    return false;
  }

  int slot_index = transfer_.slot_index;
  PersistedSlot slot = transfer_.slot;
  std::vector<uint8_t> payload = transfer_.payload;

  if (!persistSlotPayload(slot_index, payload))
  {
    resetTransfer();
    return false;
  }

  slots_[slot_index] = slot;
  if (!persistIndex())
  {
    resetTransfer();
    return false;
  }

  bool activated = activateSlot(slot_index, payload);
  log_i(
      "Stored file saved to SPIFFS id=%s slot=%d chunks=%u bytes=%u activated=%u used=%u",
      slot.file_id,
      slot_index,
      static_cast<unsigned>(transfer_.chunk_count),
      static_cast<unsigned>(payload.size()),
      static_cast<unsigned>(activated),
      static_cast<unsigned>(SPIFFS.usedBytes()));
  resetTransfer();
  return activated;
}

bool StoredFiles::getActivePcmFile(const char *fileId, StoredFileView &view)
{
  view = StoredFileView{};

  int slot_index = findSlotById(fileId);
  if (slot_index < 0 || !session_active_[slot_index])
  {
    log_i("Stored file inactive or not received in this session id=%s", fileId);
    return false;
  }

  const PersistedSlot &slot = slots_[slot_index];
  if (strcmp(slot.content_type, "audio/pcm") != 0)
  {
    log_w("Stored file id=%s has unsupported content_type=%s", slot.file_id, slot.content_type);
    return false;
  }

  if (cached_slot_index_ != slot_index)
  {
    std::vector<uint8_t> payload;
    if (!loadSlotPayload(slot_index, payload))
    {
      log_w("Failed to load stored file payload id=%s slot=%d", fileId, slot_index);
      return false;
    }
    cached_slot_index_ = slot_index;
    cached_payload_ = std::move(payload);
    log_i("Loaded stored file payload from SPIFFS into cache id=%s slot=%d bytes=%u",
          fileId,
          slot_index,
          static_cast<unsigned>(cached_payload_.size()));
  }

  if (cached_payload_.empty() && slot.size != 0)
  {
    return false;
  }

  view.data = cached_payload_.data();
  view.size = cached_payload_.size();
  view.sample_rate = slot.sample_rate;
  view.channels = static_cast<uint16_t>(slot.channels);
  log_i("Stored file ready for playback id=%s slot=%d bytes=%u sample_rate=%u channels=%u",
        fileId,
        slot_index,
        static_cast<unsigned>(view.size),
        static_cast<unsigned>(view.sample_rate),
        static_cast<unsigned>(view.channels));
  return true;
}

bool StoredFiles::mountSpiffs()
{
  if (storage_ready_)
  {
    return true;
  }

  storage_ready_ = SPIFFS.begin(true);
  if (!storage_ready_)
  {
    log_w("Failed to mount SPIFFS");
  }
  return storage_ready_;
}

bool StoredFiles::loadIndex()
{
  if (!storage_ready_)
  {
    return false;
  }

  if (!SPIFFS.exists(indexPath()))
  {
    slots_ = {};
    return true;
  }

  File file = SPIFFS.open(indexPath(), "r");
  if (!file)
  {
    log_w("Failed to open SPIFFS index file path=%s", indexPath());
    return false;
  }

  size_t index_size = file.size();
  if (index_size != sizeof(slots_))
  {
    log_w("Stored file index size mismatch actual=%u expected=%u",
          static_cast<unsigned>(index_size),
          static_cast<unsigned>(sizeof(slots_)));
    file.close();
    return false;
  }

  size_t bytes_read = file.read(reinterpret_cast<uint8_t *>(slots_.data()), sizeof(slots_));
  file.close();
  return bytes_read == sizeof(slots_);
}

bool StoredFiles::persistIndex()
{
  if (!storage_ready_)
  {
    return false;
  }

  File file = SPIFFS.open(indexPath(), "w");
  if (!file)
  {
    log_w("Failed to open SPIFFS index file for write path=%s", indexPath());
    return false;
  }

  size_t bytes_written = file.write(
      reinterpret_cast<const uint8_t *>(slots_.data()),
      sizeof(slots_));
  file.close();
  if (bytes_written != sizeof(slots_))
  {
    log_w("Failed to persist stored file index written=%u expected=%u",
          static_cast<unsigned>(bytes_written),
          static_cast<unsigned>(sizeof(slots_)));
    return false;
  }
  return true;
}

bool StoredFiles::persistSlotPayload(int slotIndex, const std::vector<uint8_t> &payload)
{
  if (!storage_ready_)
  {
    return false;
  }

  File file = SPIFFS.open(payloadPathForSlot(slotIndex), "w");
  if (!file)
  {
    log_w("Failed to open SPIFFS payload file for write slot=%d path=%s",
          slotIndex,
          payloadPathForSlot(slotIndex));
    return false;
  }

  size_t bytes_written = 0;
  if (!payload.empty())
  {
    bytes_written = file.write(payload.data(), payload.size());
  }
  file.close();
  if (bytes_written != payload.size())
  {
    log_w("Failed to persist stored file payload slot=%d written=%u expected=%u",
          slotIndex,
          static_cast<unsigned>(bytes_written),
          static_cast<unsigned>(payload.size()));
    return false;
  }
  return true;
}

bool StoredFiles::loadSlotPayload(int slotIndex, std::vector<uint8_t> &payload)
{
  payload.clear();
  if (!storage_ready_)
  {
    return false;
  }

  File file = SPIFFS.open(payloadPathForSlot(slotIndex), "r");
  if (!file)
  {
    log_w("Failed to open SPIFFS payload file for read slot=%d path=%s",
          slotIndex,
          payloadPathForSlot(slotIndex));
    return false;
  }

  size_t payload_size = file.size();
  if (payload_size != slots_[slotIndex].size)
  {
    log_w("Stored file payload size mismatch slot=%d actual=%u expected=%u",
          slotIndex,
          static_cast<unsigned>(payload_size),
          static_cast<unsigned>(slots_[slotIndex].size));
    file.close();
    return false;
  }

  payload.resize(payload_size);
  size_t bytes_read = 0;
  if (payload_size > 0)
  {
    bytes_read = file.read(payload.data(), payload_size);
  }
  file.close();
  return bytes_read == payload_size;
}

int StoredFiles::findSlotById(const char *fileId) const
{
  for (size_t i = 0; i < slots_.size(); ++i)
  {
    if (!slots_[i].used)
    {
      continue;
    }
    if (strcmp(slots_[i].file_id, fileId) == 0)
    {
      return static_cast<int>(i);
    }
  }
  return -1;
}

int StoredFiles::selectSlotForId(const char *fileId)
{
  int existing_slot = findSlotById(fileId);
  if (existing_slot >= 0)
  {
    return existing_slot;
  }

  for (size_t i = 0; i < slots_.size(); ++i)
  {
    if (!slots_[i].used)
    {
      return static_cast<int>(i);
    }
  }

  return 0;
}

void StoredFiles::resetTransfer()
{
  transfer_ = TransferState{};
}

bool StoredFiles::activateSlot(int slotIndex, const std::vector<uint8_t> &payload)
{
  if (slotIndex < 0 || slotIndex >= static_cast<int>(slots_.size()))
  {
    return false;
  }

  session_active_[slotIndex] = true;
  cached_slot_index_ = slotIndex;
  cached_payload_ = payload;
  log_i("Stored file activated for current session id=%s slot=%d bytes=%u",
        slots_[slotIndex].file_id,
        slotIndex,
        static_cast<unsigned>(cached_payload_.size()));
  return true;
}

const char *StoredFiles::payloadPathForSlot(int slotIndex)
{
  if (slotIndex < 0 || slotIndex >= static_cast<int>(sizeof(kPayloadPaths) / sizeof(kPayloadPaths[0])))
  {
    return kPayloadPaths[0];
  }
  return kPayloadPaths[slotIndex];
}

const char *StoredFiles::indexPath()
{
  return kIndexFilePath;
}
