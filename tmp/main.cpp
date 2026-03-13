#include <Ticker.h>
#include <M5Unified.h>
#include <ESP32Servo.h>

// CoreS3 Port A
// static const int SERVO_PIN1 = 1;
// static const int SERVO_PIN2 = 2;

// CoreS3 with m5-pantilt
const int SERVOX_PIN = 6;
const int SERVOY_PIN = 7;

#define DELAY_MS 40

namespace test4
{
  class LServo
  {
  protected:
    Servo servoX;
    Servo servoY;

    int8_t current_degree_x;
    int8_t current_degree_y;
    int8_t start_degree_x;
    int8_t start_degree_y;
    int8_t target_degree_x;
    int8_t target_degree_y;
    uint32_t move_start_time_x;
    uint32_t move_start_time_y;
    uint32_t move_duration_ms_x;
    uint32_t move_duration_ms_y;
    uint32_t last_update_time_ms_x;
    uint32_t last_update_time_ms_y;
    uint32_t easing_division_ms = 50;
    bool moving_x;
    bool moving_y;

  public:
    LServo()
        : current_degree_x(90), current_degree_y(90),
          start_degree_x(90), start_degree_y(90),
          target_degree_x(90), target_degree_y(90),
          move_start_time_x(0), move_start_time_y(0),
          move_duration_ms_x(0), move_duration_ms_y(0),
          last_update_time_ms_x(0), last_update_time_ms_y(0),
          moving_x(false), moving_y(false) {
          };
    void begin(int x_pin, int y_pin)
    {
      servoX.setPeriodHertz(50);
      servoX.attach(x_pin, 500, 2400);
      servoY.setPeriodHertz(50);
      servoY.attach(y_pin, 500, 2400);
      servoX.write(current_degree_x);
      servoY.write(current_degree_y);
    }
    void moveX(int16_t degree, uint32_t duration_ms)
    {
      target_degree_x = constrain(degree, 0, 180);
      start_degree_x = current_degree_x;
      move_start_time_x = millis();
      last_update_time_ms_x = move_start_time_x;
      move_duration_ms_x = duration_ms;

      if (duration_ms == 0 || start_degree_x == target_degree_x)
      {
        current_degree_x = target_degree_x;
        servoX.write(current_degree_x);
        moving_x = false;
        return;
      }

      moving_x = true;
    }
    void moveY(int16_t degree, uint32_t duration_ms)
    {
      target_degree_y = constrain(degree, 0, 180);
      start_degree_y = current_degree_y;
      move_start_time_y = millis();
      last_update_time_ms_y = move_start_time_y;
      move_duration_ms_y = duration_ms;

      if (duration_ms == 0 || start_degree_y == target_degree_y)
      {
        current_degree_y = target_degree_y;
        servoY.write(current_degree_y);
        moving_y = false;
        return;
      }

      moving_y = true;
    }
    void loop()
    {
      uint32_t now = millis();

      if (moving_x && now - last_update_time_ms_x >= easing_division_ms)
      {
        // Serial.println("@@X");
        uint32_t elapsed_ms = now - move_start_time_x;
        if (elapsed_ms >= move_duration_ms_x)
        {
          current_degree_x = target_degree_x;
          servoX.write(current_degree_x);
          moving_x = false;
        }
        else
        {
          float progress = static_cast<float>(elapsed_ms) / static_cast<float>(move_duration_ms_x);
          current_degree_x = start_degree_x + static_cast<int16_t>((target_degree_x - start_degree_x) * progress);
          servoX.write(current_degree_x);
          last_update_time_ms_x = now;
        }
      }

      if (moving_y && now - last_update_time_ms_y >= easing_division_ms)
      {
        uint32_t elapsed_ms = now - move_start_time_y;
        if (elapsed_ms >= move_duration_ms_y)
        {
          current_degree_y = target_degree_y;
          servoY.write(current_degree_y);
          moving_y = false;
        }
        else
        {
          float progress = static_cast<float>(elapsed_ms) / static_cast<float>(move_duration_ms_y);
          current_degree_y = start_degree_y + static_cast<int16_t>((target_degree_y - start_degree_y) * progress);
          servoY.write(current_degree_y);
          last_update_time_ms_y = now;
        }
      }
    }
  };

  LServo servo;
  uint32_t loop_start_time = 0;
  int8_t state = 0;

  void setup()
  {
    auto cfg = M5.config();
    M5.begin(cfg);
    Serial.begin(115200);

    M5.Display.setTextSize(2);

    servo.begin(SERVOX_PIN, SERVOY_PIN);

    M5.Display.println("SG90 Servo test (ServoEasing)");
    Serial.println("SG90 Servo test (ServoEasing)");

    delay(5000);

    loop_start_time = millis();
  }

  void loop()
  {
    M5.update();

    uint32_t now = millis();
    uint32_t elapsed_ms = now - loop_start_time;

    if (state == 0 && elapsed_ms >= 0)
    {
      Serial.println("@@1");
      servo.moveX(110, 300);
      state = 1;
      loop_start_time = now;
    }
    else if (state == 1 && elapsed_ms >= 1000)
    {
      Serial.println("@@2");
      servo.moveX(70, 1000);
      state = 2;
      loop_start_time = now;
    }
    else if (state == 2 && elapsed_ms >= 2000)
    {
      Serial.println("@@3");
      servo.moveX(90, 300);
      state = 3;
      loop_start_time = now;
    }
    else if (state == 3 && elapsed_ms >= 2000)
    {
      Serial.println("@@4");
      servo.moveY(100, 300);
      state = 4;
      loop_start_time = now;
    }
    else if (state == 4 && elapsed_ms >= 1000)
    {
      Serial.println("@@5");
      servo.moveY(80, 1000);
      state = 5;
      loop_start_time = now;
    }
    else if (state == 5 && elapsed_ms >= 2000)
    {
      Serial.println("@@6");
      servo.moveY(90, 300);
      state = 6;
      loop_start_time = now;
    }
    else if (state == 6 && elapsed_ms >= 2000)
    {
      Serial.println("@@7");
      servo.moveY(80, 200);
      state = 7;
      loop_start_time = now;
    }
    else if (state == 7 && elapsed_ms >= 3000)
    {
      Serial.println("@@8");
      servo.moveY(100, 100);
      state = 8;
      loop_start_time = now;
    }
    else if (state == 8 && elapsed_ms >= 300)
    {
      Serial.println("@@9");
      servo.moveY(90, 100);
      state = 9;
      loop_start_time = now;
    }
    else if (state == 9 && elapsed_ms >= 300)
    {
      Serial.println("@@10");
      servo.moveY(100, 100);
      state = 10;
      loop_start_time = now;
    }
    else if (state == 10 && elapsed_ms >= 300)
    {
      Serial.println("@@11");
      servo.moveY(90, 100);
      state = 11;
      loop_start_time = now;
    }
    else if (state == 11 && elapsed_ms >= 5000)
    {
      Serial.println("@@12");
      state = 0;
      loop_start_time = now;
    }

    servo.loop();
  }
}
