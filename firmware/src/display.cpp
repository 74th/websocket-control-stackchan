#include "display.hpp"

Display::Display(StateMachine &stateMachine) : state_(stateMachine) {}

void Display::init()
{
  M5.Display.clear();
  M5.Display.setTextSize(2);
  drawForState(state_.getState());
  drawFace();
  has_prev_state_ = true;
  prev_state_ = state_.getState();
}

void Display::loop()
{
  StateMachine::State current = state_.getState();
  if (!has_prev_state_ || current != prev_state_)
  {
    M5.Display.fillScreen(TFT_BLACK);
    drawForState(current);
    drawFace();
  }

  prev_state_ = current;
  has_prev_state_ = true;
}

void Display::drawForState(StateMachine::State state)
{
  uint16_t bg_color;
  uint16_t font_color;

  switch (state)
  {
  case StateMachine::Idle:
    bg_color = TFT_DARKGRAY;
    font_color = TFT_WHITE;
    break;
  case StateMachine::Listening:
    bg_color = TFT_BLUE;
    font_color = TFT_WHITE;
    break;
  case StateMachine::Thinking:
    bg_color = TFT_ORANGE;
    font_color = TFT_BLACK;
    break;
  case StateMachine::Speaking:
    bg_color = TFT_GREEN;
    font_color = TFT_BLACK;
    break;
  case StateMachine::Disconnected:
    bg_color = TFT_RED;
    font_color = TFT_WHITE;
    break;
  default:
    bg_color = TFT_DARKGRAY;
    font_color = TFT_WHITE;
    break;
  }

  M5.Display.fillRect(0, 220, 320, 240, bg_color);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(font_color, bg_color);
  M5.Display.setCursor(10, 222);
  M5.Display.printf("%s", stateToString(state));
}

void Display::drawFace()
{
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
