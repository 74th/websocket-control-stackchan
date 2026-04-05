#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <vector>

#include "config.h"
#include "protocols.hpp"

#if defined(USE_SERVO_SG90)
#include <ESP32Servo.h>
#endif

#if defined(USE_SERVO_SCS0009)
#include <SCServo.h>
#endif

class BodyServo
{
public:
  BodyServo() = default;

  void init();
  void loop();
  void resetSequence();

  bool enqueueSequence(const uint8_t *payload, size_t payload_len);
  bool isBusy() const;
  void setCompletionCallback(std::function<void()> cb);

private:
  struct AxisMotion
  {
#if defined(USE_SERVO_SG90)
    Servo servo;
#endif
#if defined(USE_SERVO_SCS0009)
    uint8_t scs_id = 0;
    bool reverse_direction = false;
#endif
    int16_t center_offset_degree = 0;
    int16_t current_degree = 90;
    int16_t start_degree = 90;
    int16_t target_degree = 90;
    uint32_t move_start_ms = 0;
    uint32_t move_duration_ms = 0;
    uint32_t last_update_ms = 0;
    bool moving = false;
  };

  struct Step
  {
    ServoCommandOp op;
    int8_t angle = 0;
    int16_t duration_ms = 0;
  };

  bool ensureAttached();
  void updateAxis(AxisMotion &axis, uint32_t now);
  void startMove(AxisMotion &axis, int8_t degree, int16_t duration_ms);
  void startCurrentStep(uint32_t now);
  void advanceStep();
  void completeSequence();

  AxisMotion axis_x_{};
  AxisMotion axis_y_{};
#if defined(USE_SERVO_SCS0009)
  SCSCL sc_{};
#endif
  bool attached_ = false;

  std::vector<Step> steps_{};
  size_t current_step_index_ = 0;
  bool sequence_active_ = false;
  bool step_started_ = false;
  uint32_t sleep_deadline_ms_ = 0;
  std::function<void()> on_complete_{};
};
