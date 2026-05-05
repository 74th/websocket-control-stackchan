#pragma once

#if USE_STACKCHAN_BSP
#include <M5StackChan.h>
#else
#include <M5Unified.h>
#endif
#include "state_machine.hpp"

class Display
{
public:
  explicit Display(StateMachine &stateMachine);

  void init();
  void loop();

private:
  void drawForState(StateMachine::State state);
  void drawFace();
  bool isAtomS3R() const;
  int32_t statusBarHeight() const;

  StateMachine &state_;
  bool has_prev_state_ = false;
  StateMachine::State prev_state_ = StateMachine::Idle;
};
