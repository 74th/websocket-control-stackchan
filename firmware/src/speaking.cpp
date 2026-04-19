#include "speaking.hpp"
#include <utility>

void Speaking::reset()
{
  buffer_[0].clear();
  buffer_[1].clear();
  buffer_[2].clear();
  current_buffer_ = 0;
  playing_ = false;
  mic_was_enabled_ = false;
  streaming_ = false;
  next_seq_ = 0;
  sample_rate_ = 24000; // default fallback
  channels_ = 1;
}

void Speaking::init()
{
  reset();
}

void Speaking::begin()
{
  // 念のためマイクを停止し、再生に集中させる
  M5.Mic.end();
}

void Speaking::end()
{
  if (M5.Speaker.isPlaying())
  {
    M5.Speaker.stop();
  }
  M5.Speaker.end();
  reset();
}

void Speaking::handleWavStart(uint32_t seq, uint32_t sampleRate, uint16_t channels)
{
  current_buffer_ = (current_buffer_ + 1) % 3;
  std::vector<uint8_t> &buf = buffer_[current_buffer_];
  buf.clear();
  playing_ = false;
  streaming_ = true;
  next_seq_ = seq + 1;
  state_.setState(StateMachine::Speaking);

  if (sampleRate > 0)
  {
    sample_rate_ = sampleRate;
  }
  if (channels > 0)
  {
    channels_ = channels;
  }

  log_i("TTS meta: sample_rate=%u channels=%u", (unsigned)sample_rate_, (unsigned)channels_);
  log_i("TTS stream start seq=%u", (unsigned)seq);
}

void Speaking::handleWavData(uint32_t seq, const uint8_t *body, size_t bodyLen)
{
  if (!streaming_)
  {
    return;
  }

  std::vector<uint8_t> &buf = buffer_[current_buffer_];

  if (seq != next_seq_)
  {
    log_w("TTS seq gap: got=%u expected=%u", (unsigned)seq, (unsigned)next_seq_);
    // TCP 前提で再送しない。検知だけして次を受ける。
    next_seq_ = seq + 1;
  }
  else
  {
    next_seq_++;
  }

  buf.insert(buf.end(), body, body + bodyLen);
  log_d("TTS chunk size=%u recv=%u", (unsigned)bodyLen, (unsigned)buf.size());
}

void Speaking::handleWavEnd(uint32_t seq)
{
  if (!streaming_)
  {
    return;
  }

  if (seq != next_seq_)
  {
    log_w("TTS end seq gap: got=%u expected=%u", (unsigned)seq, (unsigned)next_seq_);
  }

  std::vector<uint8_t> &buf = buffer_[current_buffer_];
  streaming_ = false;
  next_seq_ = 0;

  if (!buf.empty())
  {
    playing_ = true;

    const int16_t *samples = reinterpret_cast<const int16_t *>(buf.data());
    size_t sample_len = buf.size() / sizeof(int16_t);
    bool stereo = channels_ > 1;
    M5.Speaker.playRaw(samples, sample_len, sample_rate_, stereo, 1, 0);
  }
}

void Speaking::loop()
{
  if (playing_ && !M5.Speaker.isPlaying())
  {
    log_i("TTS play done");
    if (on_speak_finished_)
    {
      on_speak_finished_();
    }
    delay(10);
    state_.setState(StateMachine::Idle);
  }
}

void Speaking::setSpeakFinishedCallback(std::function<void()> cb)
{
  on_speak_finished_ = std::move(cb);
}
