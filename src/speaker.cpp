#include "speaker.hpp"
#include <cstring>

void Speaker::reset()
{
  buffer_.clear();
  ready_ = false;
  playing_ = false;
  mic_was_enabled_ = false;
  streaming_ = false;
  next_seq_ = 0;
  sample_rate_ = 24000; // default fallback
  channels_ = 1;
}

void Speaker::init()
{
  reset();
}

void Speaker::handleWavMessage(const WsHeader &hdr, const uint8_t *body, size_t bodyLen)
{
  auto msgType = static_cast<MessageType>(hdr.messageType);

  if (msgType == MessageType::START)
  {
    buffer_.clear();
    ready_ = false;
    playing_ = false;
    streaming_ = true;
    next_seq_ = hdr.seq + 1;

    // START payload (optional): <uint32 sample_rate><uint16 channels>
    if (body && bodyLen >= 6)
    {
      uint32_t sr = 0;
      uint16_t ch = 1;
      memcpy(&sr, body, sizeof(sr));
      memcpy(&ch, body + sizeof(sr), sizeof(ch));
      if (sr > 0)
      {
        sample_rate_ = sr;
      }
      if (ch > 0)
      {
        channels_ = ch;
      }
      log_i("TTS meta: sample_rate=%u channels=%u", (unsigned)sample_rate_, (unsigned)channels_);
    }
    else
    {
      log_w("TTS START without meta, fallback sr=%u ch=%u", (unsigned)sample_rate_, (unsigned)channels_);
    }
    M5.Display.println("Recv TTS START");
    log_i("TTS stream start seq=%u", (unsigned)hdr.seq);
    return;
  }

  if (msgType == MessageType::DATA)
  {
    if (!streaming_)
    {
      M5.Display.println("TTS DATA without START");
      return;
    }

    if (hdr.seq != next_seq_)
    {
      log_w("TTS seq gap: got=%u expected=%u", (unsigned)hdr.seq, (unsigned)next_seq_);
      // TCP 前提で再送しない。検知だけして次を受ける。
      next_seq_ = hdr.seq + 1;
    }
    else
    {
      next_seq_++;
    }

    buffer_.insert(buffer_.end(), body, body + bodyLen);
    log_d("TTS chunk size=%u recv=%u", (unsigned)bodyLen, (unsigned)buffer_.size());
    return;
  }

  if (msgType == MessageType::END)
  {
    if (!streaming_)
    {
      M5.Display.println("TTS END without START");
      return;
    }
    streaming_ = false;
    next_seq_ = 0;
    if (!buffer_.empty())
    {
      ready_ = true;
      M5.Display.printf("TTS ready: %u bytes\n", (unsigned)buffer_.size());
    }
    return;
  }
}

void Speaker::loop()
{
  // start playback when ready and not already playing
  if (ready_ && !playing_)
  {
    if (buffer_.empty())
    {
      ready_ = false;
      return;
    }

    if (buffer_.size() % sizeof(int16_t) != 0)
    {
      log_w("TTS buffer not aligned to 16-bit samples: %u bytes", (unsigned)buffer_.size());
      buffer_.clear();
      ready_ = false;
      return;
    }

    M5.Speaker.stop();
    M5.Display.println("Playing TTS...");
    mic_was_enabled_ = M5.Mic.isEnabled();
    if (mic_was_enabled_)
    {
      M5.Mic.end();
      log_i("Mic stopped for TTS playback");
      delay(10);
    }

    log_i("TTS play start size=%u", (unsigned)buffer_.size());
    const int16_t *samples = reinterpret_cast<const int16_t *>(buffer_.data());
    size_t sample_len = buffer_.size() / sizeof(int16_t);
    bool stereo = channels_ > 1;
    M5.Speaker.playRaw(samples, sample_len, sample_rate_, stereo, 1, 0);
    playing_ = true;
    ready_ = false;
  }

  if (playing_ && !M5.Speaker.isPlaying())
  {
    log_i("TTS play done");
    M5.Speaker.stop();
    M5.Speaker.end();
    delay(10);
    buffer_.clear();
    playing_ = false;
    streaming_ = false;
    ready_ = false;
    M5.Display.println("TTS done.");

    if (mic_was_enabled_ && !M5.Mic.isEnabled())
    {
      M5.Mic.begin();
      log_i("Mic restarted after TTS playback");
    }
  }
}
