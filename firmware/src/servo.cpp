#include "servo.hpp"

#include <M5Unified.h>

#include <algorithm>
#include <cstring>
#include <utility>

namespace
{
constexpr int kServoXPin = 6;
constexpr int kServoYPin = 7;
constexpr int kServoPulseMinUs = 500;
constexpr int kServoPulseMaxUs = 2400;
constexpr int kServoFrequencyHz = 50;
constexpr uint32_t kEasingDivisionMs = 10;

int16_t clampDegree(int16_t degree)
{
  return std::clamp<int16_t>(degree, 0, 180);
}

uint32_t clampDuration(int16_t duration_ms)
{
  return duration_ms <= 0 ? 0U : static_cast<uint32_t>(duration_ms);
}

int16_t readInt16Le(const uint8_t *src)
{
  int16_t value = 0;
  memcpy(&value, src, sizeof(value));
  return value;
}
} // namespace

void BodyServo::init()
{
  if (!ensureAttached())
  {
    log_w("Failed to attach servos");
    return;
  }

  axis_x_.servo.write(axis_x_.current_degree);
  axis_y_.servo.write(axis_y_.current_degree);
}

void BodyServo::loop()
{
  if (!attached_)
  {
    return;
  }

  uint32_t now = millis();
  updateAxis(axis_x_, now);
  updateAxis(axis_y_, now);

  if (!sequence_active_ || current_step_index_ >= steps_.size())
  {
    return;
  }

  if (!step_started_)
  {
    startCurrentStep(now);
  }

  if (!sequence_active_ || current_step_index_ >= steps_.size())
  {
    return;
  }

  const Step &step = steps_[current_step_index_];
  bool finished = false;
  switch (step.op)
  {
  case ServoCommandOp::Sleep:
    finished = static_cast<int32_t>(now - sleep_deadline_ms_) >= 0;
    break;
  case ServoCommandOp::MoveX:
    finished = !axis_x_.moving;
    break;
  case ServoCommandOp::MoveY:
    finished = !axis_y_.moving;
    break;
  default:
    log_w("Unknown servo step op=%u", static_cast<unsigned>(step.op));
    finished = true;
    break;
  }

  if (finished)
  {
    advanceStep();
  }
}

void BodyServo::resetSequence()
{
  steps_.clear();
  current_step_index_ = 0;
  sequence_active_ = false;
  step_started_ = false;
  sleep_deadline_ms_ = 0;
  axis_x_.moving = false;
  axis_y_.moving = false;
}

bool BodyServo::enqueueSequence(const uint8_t *payload, size_t payload_len)
{
  if (!ensureAttached())
  {
    return false;
  }
  if (payload == nullptr || payload_len < 1)
  {
    log_w("ServoCmd payload too short: %u", static_cast<unsigned>(payload_len));
    return false;
  }

  const uint8_t command_count = payload[0];
  size_t offset = 1;
  std::vector<Step> parsed_steps;
  parsed_steps.reserve(command_count);

  for (uint8_t i = 0; i < command_count; ++i)
  {
    if (offset >= payload_len)
    {
      log_w("ServoCmd truncated at command=%u", static_cast<unsigned>(i));
      return false;
    }

    const ServoCommandOp op = static_cast<ServoCommandOp>(payload[offset++]);
    Step step{};
    step.op = op;

    switch (op)
    {
    case ServoCommandOp::Sleep:
      if (offset + sizeof(int16_t) > payload_len)
      {
        log_w("ServoCmd sleep truncated at command=%u", static_cast<unsigned>(i));
        return false;
      }
      step.duration_ms = readInt16Le(payload + offset);
      offset += sizeof(int16_t);
      break;
    case ServoCommandOp::MoveX:
    case ServoCommandOp::MoveY:
      if (offset + sizeof(int8_t) + sizeof(int16_t) > payload_len)
      {
        log_w("ServoCmd move truncated at command=%u", static_cast<unsigned>(i));
        return false;
      }
      step.angle = static_cast<int8_t>(payload[offset]);
      offset += sizeof(int8_t);
      step.duration_ms = readInt16Le(payload + offset);
      offset += sizeof(int16_t);
      break;
    default:
      log_w("ServoCmd unknown op=%u", static_cast<unsigned>(op));
      return false;
    }

    parsed_steps.push_back(step);
  }

  if (offset != payload_len)
  {
    log_w("ServoCmd payload has %u trailing bytes", static_cast<unsigned>(payload_len - offset));
    return false;
  }

  resetSequence();
  steps_ = std::move(parsed_steps);

  if (steps_.empty())
  {
    completeSequence();
    return true;
  }

  current_step_index_ = 0;
  sequence_active_ = true;
  step_started_ = false;
  log_i("Accepted servo sequence commands=%u", static_cast<unsigned>(command_count));
  return true;
}

bool BodyServo::isBusy() const
{
  return sequence_active_ || axis_x_.moving || axis_y_.moving;
}

void BodyServo::setCompletionCallback(std::function<void()> cb)
{
  on_complete_ = std::move(cb);
}

bool BodyServo::ensureAttached()
{
  if (attached_)
  {
    return true;
  }

  axis_x_.servo.setPeriodHertz(kServoFrequencyHz);
  axis_y_.servo.setPeriodHertz(kServoFrequencyHz);

  const bool x_ok = axis_x_.servo.attach(kServoXPin, kServoPulseMinUs, kServoPulseMaxUs) > 0;
  const bool y_ok = axis_y_.servo.attach(kServoYPin, kServoPulseMinUs, kServoPulseMaxUs) > 0;
  attached_ = x_ok && y_ok;
  return attached_;
}

void BodyServo::updateAxis(AxisMotion &axis, uint32_t now)
{
  if (!axis.moving)
  {
    return;
  }

  const uint32_t elapsed = now - axis.move_start_ms;
  if ((now - axis.last_update_ms) < kEasingDivisionMs && elapsed < axis.move_duration_ms)
  {
    return;
  }

  if (elapsed >= axis.move_duration_ms)
  {
    axis.current_degree = axis.target_degree;
    axis.servo.write(axis.current_degree);
    axis.moving = false;
    axis.last_update_ms = now;
    return;
  }

  const float progress = static_cast<float>(elapsed) / static_cast<float>(axis.move_duration_ms);
  axis.current_degree = axis.start_degree + static_cast<int16_t>((axis.target_degree - axis.start_degree) * progress);
  axis.servo.write(axis.current_degree);
  axis.last_update_ms = now;
}

void BodyServo::startMove(AxisMotion &axis, int8_t degree, int16_t duration_ms)
{
  axis.target_degree = clampDegree(degree);
  axis.start_degree = axis.current_degree;
  axis.move_start_ms = millis();
  axis.last_update_ms = axis.move_start_ms;
  axis.move_duration_ms = clampDuration(duration_ms);

  if (axis.move_duration_ms == 0 || axis.start_degree == axis.target_degree)
  {
    axis.current_degree = axis.target_degree;
    axis.servo.write(axis.current_degree);
    axis.moving = false;
    return;
  }

  axis.moving = true;
}

void BodyServo::startCurrentStep(uint32_t now)
{
  if (!sequence_active_ || current_step_index_ >= steps_.size())
  {
    return;
  }

  const Step &step = steps_[current_step_index_];
  step_started_ = true;
  switch (step.op)
  {
  case ServoCommandOp::Sleep:
    sleep_deadline_ms_ = now + clampDuration(step.duration_ms);
    break;
  case ServoCommandOp::MoveX:
    startMove(axis_x_, step.angle, step.duration_ms);
    break;
  case ServoCommandOp::MoveY:
    startMove(axis_y_, step.angle, step.duration_ms);
    break;
  default:
    advanceStep();
    break;
  }
}

void BodyServo::advanceStep()
{
  if (!sequence_active_)
  {
    return;
  }

  ++current_step_index_;
  step_started_ = false;
  if (current_step_index_ >= steps_.size())
  {
    completeSequence();
  }
}

void BodyServo::completeSequence()
{
  steps_.clear();
  current_step_index_ = 0;
  sequence_active_ = false;
  step_started_ = false;
  sleep_deadline_ms_ = 0;
  log_i("Servo sequence completed");
  if (on_complete_)
  {
    on_complete_();
  }
}
