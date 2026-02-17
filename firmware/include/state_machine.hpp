#pragma once

#include <array>
#include <functional>
#include <stdint.h>
#include <vector>

class StateMachine
{
public:
  enum State : uint8_t
  {
    Idle = 0,
    Listening = 1,
  };

  StateMachine() = default;

  void setState(State s);
  State getState() const;
  bool isIdle() const;
  bool isListening() const;

  using Callback = std::function<void(State prev, State next)>;
  void addStateEntryEvent(State state, Callback cb);
  void addStateExitEvent(State state, Callback cb);

private:
  State state_ = Idle;
  std::array<std::vector<Callback>, 2> entry_events_{};
  std::array<std::vector<Callback>, 2> exit_events_{};
};
