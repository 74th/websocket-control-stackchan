// Wifi
#define WIFI_SSID_H "__SSID__"
#define WIFI_PASSWORD_H "__PASSWORD__"

// WebSocket Server
#define SERVER_HOST_H "192.168.1.179"  // Example: server IP
#define SERVER_PORT_H 8000              // Example: FastAPI port
#define SERVER_PATH_H "/ws/stackchan"  // WebSocket path

// -- using SG90 --
#define USE_SERVO_SG90 1

// CoreS3 PortA
// #define SERVO_SG90_X_PIN 1
// #define SERVO_SG90_Y_PIN 2
// CoreS3 PortC
#define SERVO_SG90_X_PIN 18
#define SERVO_SG90_Y_PIN 17
// m5pantilt
// #define SERVO_SG90_X_PIN 7
// #define SERVO_SG90_Y_PIN 6
// Center offset added to the logical 90-degree center
// Positive values bias X to the right and Y upward; negative values bias X to the left and Y downward
// #define SERVO_SG90_X_CENTER_OFFSET 0
// #define SERVO_SG90_Y_CENTER_OFFSET 0

// -- using SCS0009 --
// #define USE_SERVO_SCS0009 1

// CoreS3 PortC
// #define SCS_SRIAL_RX_PIN 17
// #define SCS_SRIAL_TX_PIN 18

// #define SCS0009_X_ID 1
// #define SCS0009_Y_ID 2
// Center offset added to the logical 90-degree center
// Positive values bias X to the right and Y upward; negative values bias X to the left and Y downward
// #define SCS0009_X_CENTER_OFFSET 0
// #define SCS0009_Y_CENTER_OFFSET 0
