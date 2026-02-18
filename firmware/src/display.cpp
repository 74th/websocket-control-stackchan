#include "display.hpp"

Display::Display(StateMachine &stateMachine) : state_(stateMachine) {}

void Display::init()
{
  M5.Display.clear();
  M5.Display.setTextSize(2);
  drawForState(state_.getState());
  has_prev_state_ = true;
  prev_state_ = state_.getState();
}

void Display::loop()
{
  StateMachine::State current = state_.getState();
  if (has_prev_state_ && current == prev_state_)
  {
    return;
  }

  drawForState(current);
  prev_state_ = current;
  has_prev_state_ = true;
}

void Display::drawForState(StateMachine::State state)
{
  uint16_t bg = colorForState(state);
  M5.Display.fillScreen(bg);
}

uint16_t Display::colorForState(StateMachine::State state)
{
  switch (state)
  {
  case StateMachine::Idle:
    return TFT_BLACK;
  case StateMachine::Listening:
    return TFT_BLUE;
  case StateMachine::Speaking:
    return TFT_GREEN;
  default:
    return TFT_DARKGREY;
  }
}
