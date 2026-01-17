#pragma once

#include <stdint.h>

class StateMachine
{
public:
  enum State : uint8_t
  {
    Idle = 0,
    Streaming = 1,
  };

  StateMachine() = default;

  void setState(State s) { state_ = s; }
  State getState() const { return state_; }
  bool isIdle() const { return state_ == Idle; }
  bool isStreaming() const { return state_ == Streaming; }

private:
  State state_ = Idle;
};
