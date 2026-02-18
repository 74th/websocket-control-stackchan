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
  if (!has_prev_state_ || current != prev_state_)
  {
    drawForState(current);
  }

  prev_state_ = current;
  has_prev_state_ = true;
}

void Display::drawForState(StateMachine::State state)
{
  uint16_t bg = colorForState(state);
  M5.Display.fillScreen(bg);

  uint32_t eye_y = 102;
  uint32_t between_eyes = 135;
  uint32_t eye_size = 8;
  uint32_t mouth_y = 157;
  uint32_t mouth_width = 85;
  uint32_t mouth_height = 4;
  M5.Display.fillCircle(160 - between_eyes / 2, eye_y, eye_size, TFT_WHITE);
  M5.Display.fillCircle(160 + between_eyes / 2, eye_y, eye_size, TFT_WHITE);
  M5.Display.fillRect(160 - mouth_width / 2, mouth_y, mouth_width, mouth_height, TFT_WHITE);
}

uint16_t Display::colorForState(StateMachine::State state)
{
  switch (state)
  {
  case StateMachine::Idle:
    return TFT_BLACK;
  case StateMachine::Listening:
    return TFT_BLUE;
  case StateMachine::Thinking:
    return TFT_ORANGE;
  case StateMachine::Speaking:
    return TFT_GREEN;
  case StateMachine::Disconnected:
    return TFT_RED;
  default:
    return TFT_DARKGREY;
  }
}
