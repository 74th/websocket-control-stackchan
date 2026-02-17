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

  void setState(State s);
  State getState() const;
  bool isIdle() const;
  bool isStreaming() const;

private:
  State state_ = Idle;
};
