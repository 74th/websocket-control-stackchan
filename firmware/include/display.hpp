#pragma once

#include <M5Unified.h>
#include "state_machine.hpp"

class Display
{
public:
  explicit Display(StateMachine &stateMachine);

  void init();
  void loop();

private:
  void drawForState(StateMachine::State state);
  static uint16_t colorForState(StateMachine::State state);

  StateMachine &state_;
  bool has_prev_state_ = false;
  StateMachine::State prev_state_ = StateMachine::Idle;
};
