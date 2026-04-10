#include <algorithm>

#include "display.hpp"

Display::Display(StateMachine &stateMachine) : state_(stateMachine) {}

void Display::init()
{
  M5.Display.fillScreen(TFT_BLACK);
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
  int32_t width = M5.Display.width();
  int32_t height = M5.Display.height();
  int32_t bar_height = statusBarHeight();
  int32_t bar_y = std::max<int32_t>(0, height - bar_height);

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

  M5.Display.fillRect(0, bar_y, width, bar_height, bg_color);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(font_color, bg_color);
  M5.Display.setCursor(isAtomS3R() ? 4 : 10, bar_y + (isAtomS3R() ? 6 : 2));
  M5.Display.printf("%s", stateToString(state));
}

void Display::drawFace()
{
  int32_t width = M5.Display.width();
  int32_t height = M5.Display.height() - statusBarHeight();
  int32_t center_x = width / 2;

  int32_t eye_y = height * (isAtomS3R() ? 42 : 46) / 100;
  int32_t eye_offset_x = width * (isAtomS3R() ? 18 : 21) / 100;
  int32_t eye_radius = std::max<int32_t>(4, std::min(width, height) / (isAtomS3R() ? 20 : 24));

  int32_t mouth_y = height * (isAtomS3R() ? 68 : 71) / 100;
  int32_t mouth_width = width * (isAtomS3R() ? 32 : 27) / 100;
  int32_t mouth_height = std::max<int32_t>(3, height / (isAtomS3R() ? 36 : 48));

  M5.Display.fillCircle(center_x - eye_offset_x, eye_y, eye_radius, TFT_WHITE);
  M5.Display.fillCircle(center_x + eye_offset_x, eye_y, eye_radius, TFT_WHITE);
  M5.Display.fillRect(center_x - mouth_width / 2, mouth_y, mouth_width, mouth_height, TFT_WHITE);
}

bool Display::isAtomS3R() const
{
#if defined(ARDUINO_M5STACK_ATOMS3R)
  return true;
#else
  return false;
#endif
}

int32_t Display::statusBarHeight() const
{
  return isAtomS3R() ? 28 : 20;
}
