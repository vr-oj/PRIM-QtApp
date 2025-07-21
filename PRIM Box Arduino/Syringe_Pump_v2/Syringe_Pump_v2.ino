/*MODIFIED FOR USE WITH SYRINGE PUMP BOARD, **NOT** BUTI BOARD AS ORIGINALLY USED!!*/

#include <Arduino.h>
#include <Wire.h>
#include "FlashStorage.h"
#include "avr/dtostrf.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include "FreeSansBold7pt7b.h"
#include "FreeSansBold8pt7b.h"
#include "FreeSansBold9pt7b.h"
#include <Adafruit_ST7735.h>  // Hardware-specific library

/*TFT Setup*/
#define TFT_CS A4
#define TFT_DC A3
#define TFT_RST -1  // Or set to -1 and connect to Arduino RESET pin
Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

/*Rotary Encoder Setup and interrups*/
static int pinA = 11;
static int pinB = 12;
static int enSW = 13;
volatile byte aFlag = 0;        //  let's us know when we're expecting a rising edge on pinDT to signal that the encoder has arrived at a detent
volatile byte bFlag = 0;        //  let's us know when we're expecting a rising edge on pinCLK to signal that the encoder has arrived at a detent (opposite direction to when aFlag is set)
int encoderPos;                 //  this variable stores our current value of encoder position. Change to int or uin16_t instead of byte if you want to record a larger range than 0-255
volatile uint32_t reading = 0;  //  somewhere to store the direct values we read from our interrupt pins before checking to see if we have moved a whole detent
uint32_t maskA;
uint32_t maskB;
uint32_t maskAB;
volatile uint32_t *port;
bool box;
int runState = 0;
int choice;

void fPinA() {
  noInterrupts();
  reading = *port & maskAB;
  if ((reading == maskAB) && aFlag) {  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos--;                      //decrement the encoder's position count
    box = !box;
    bFlag = 0;  //reset flags for the next turn
    aFlag = 0;  //reset flags for the next turn
  } else if (reading == maskB) bFlag = 1;
  interrupts();  //signal that we're expecting pinB to signal the transition to detent from free rotation
}
void fPinB() {
  noInterrupts();
  reading = *port & maskAB;
  if (reading == maskAB && bFlag) {  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos++;                    //increment the encoder's position count
    box = !box;
    bFlag = 0;  //reset flags for the next turn
    aFlag = 0;  //reset flags for the next turn
  } else if (reading == maskA) aFlag = 1;
  interrupts();  //signal that we're expecting pinA to signal the transition to detent from free rotation
}

/*Stepper Setup*/
int step = 9;  //Motor driver pin for stepping.
int dir = 10;  //Motor driver pin for motor direction.
int en = 7;    //Motor driver pin for engaging. Must be LOW in order to run motor.
int vHi = 5;   //Pin to put 5 V over the other pins needed to engage the stepper driver

//Next two pins determine microstepping. See datasheet for appropriate driver for specs. I think some BigTreeTech boards are backwards in pinout for this.
int m0 = 4;
int m1 = 0;

double stepAngle = 1.8;     //in deg. Change depending on stepper; usually 0.9 or 1.8 degress
double screwLead = 1.0583;  //in mm. Change based on TPI converted to mm. 5/16"-24 screw is 1.0583.  This is NOT pitch.
int stepFraction;          //Use the denominator. so for 1/4, use 4; for 1/16 use 16, etc.
double stepDistance;
double stepsPerMicroliter;

unsigned long current_us;
unsigned long previous_us = 0;
float tempRate = 0.0;
float actualRate = 0.0;
float actualVolume;
unsigned long stepCounter = 0;

/*External Trigger Setup*/
#define extTrigger 2

/*Syringe pump variables*/
bool trigger;

struct init_matrix {
  float syringeVol;
  int flowRate;  //in ul/min.
  int syringe;
  int syringeSize;
} startup;

const char *syringeName;  //Syringe volume. TEN or TWENTY
unsigned long timeDiff;
float volPumped;

/*Initialize Flash Storage*/
FlashStorage(initialize, init_matrix);


/*Miscellaneous global variables*/
unsigned long previousMillis = 0;
unsigned long startMillis;
unsigned long currentMillis;
double currentTime;
bool UseStartTime = true;
char number[8];
char selected[4];
char rate[6];
char volume[4];
char diagnostic[32];

void setup() {
  Serial.begin(115200);
  pinMode(enSW, INPUT_PULLUP);
  pinMode(pinB, INPUT_PULLUP);
  pinMode(pinA, INPUT_PULLUP);
  attachInterrupt(pinA, fPinA, CHANGE);  //Sets interrupt for rotary encoder so that it works with above functions;
  attachInterrupt(pinB, fPinB, CHANGE);
  maskA = digitalPinToBitMask(pinA);
  maskB = digitalPinToBitMask(pinB);
  maskAB = maskA | maskB;
  port = portInputRegister(digitalPinToPort(pinA));
  stepFraction = 64;        //dependent on the state of m0 and m1 as defined below.
  stepDistance = screwLead / (360 / (stepAngle / stepFraction));
  pinMode(extTrigger, INPUT_PULLDOWN);
  tft.initR(INITR_GREENTAB);
  tft.initR(INITR_BLACKTAB);
  tft.fillScreen(ST7735_BLACK);
  tft.setRotation(1);
  tft.setTextWrap(false);
  
  pinMode(step, OUTPUT);
  pinMode(dir, OUTPUT);
  pinMode(en, OUTPUT);
  pinMode(m0, OUTPUT);
  pinMode(m1, OUTPUT);
  pinMode(vHi, OUTPUT);
  digitalWrite(step, LOW);
  digitalWrite(dir, LOW);   //LOW is CW. HIGH is CCW.
  digitalWrite(en, HIGH);   //LOW is engaged; HIGH is disengaged.
  digitalWrite(vHi, LOW);   //LOW keeps temps down.

  bootup();
  runState = 2;
  digitalWrite(en, LOW);
  digitalWrite(vHi, HIGH);
  //m0-m1:  LOW-LOW is 1/8; LOW-HI is 1/32; HI-LOW is 1/64; HI-HI is 1/16
  digitalWrite(m0, HIGH);
  digitalWrite(m1, LOW);

  tft.fillScreen(ST7735_BLACK);
}

void loop() {
  if (runState == 0) {
    isRunning();
  }
  else if (runState == 1) {
    isChanging();
  }
  else if (runState == 2) {
    isStopping();
  }
  else if (runState == 3) {
    isPurging();
  }
  else if (runState == 4) {
    isFilling();
  }
}
//************************************************************************************************************************//

void bootup() {
  startup = initialize.read();
  initScreen();
  selectSyringe();
  selectVolume();
  selectRate();
  selectTrigger();
  delay(100);
  initialize.write(startup);
  delay(100);
  stepsPerMicroliter = StepsPerMic(syringeName);
}

void initScreen() {
  printWords(9, 1, 30, 19, 0x64df, "Initialization");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Syringe:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 59, 0x04d3, "Vol (ml):");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "uL/min:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  printWords(9, 1, 2, 99, 0x04d3, "Trigger:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
}

void selectSyringe() {
  const char *syringeMenu[] = { "10 mL", "20 mL" };
  encoderPos = startup.syringe;
  while (digitalRead(enSW)) {
    encoderLimit(0, 1);
    int position = encoderPos;
    listBox(89, 27, 70, 14, ST77XX_BLACK);
    printWords(9, 1, 90, 39, ST77XX_WHITE, syringeMenu[position]);
    choice = position;
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 90, 39, 0xfb2c, syringeMenu[choice]);
  }
  if (choice == 0) {
    startup.syringeSize = 10;
    syringeName = "TEN";
    startup.syringe = 0;
  }
  if (choice == 1) {
    startup.syringeSize = 20;
    syringeName = "TWENTY";
    startup.syringe = 1;
  }
}

float selectVolume() {
  float sizeTemp = startup.syringeSize * 10;
  float encoderTemp;
  if (startup.syringeVol > 0) {
    encoderPos = ((startup.syringeVol - startup.syringeSize) * 10);
  }
  else {
    encoderPos = 0;
  }
  char buffer[6];
  float converted;
  while (digitalRead(enSW)) {
    encoderLimit(-sizeTemp, 0);
    encoderTemp = encoderPos;
    float multiplier = (encoderTemp / 10);
    converted = startup.syringeSize + multiplier;
    // dtostrf(converted, 6, 2, buffer);
    sprintf(buffer, " %.1f ", converted);
    printWords(0, 2, 86, 47, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    startup.syringeVol = converted;
    printWords(0, 2, 86, 47, 0xfb2c, buffer);
  }
  return startup.syringeVol;
}

int selectRate() {
  char buffer[3];
  encoderPos = startup.flowRate;
  while (digitalRead(enSW)) {
    encoderLimit(1, 1000);
    sprintf(buffer, " %3d", encoderPos);
    printWords(0, 2, 86, 67, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    startup.flowRate = encoderPos;
    printWords(0, 2, 86, 67, 0xfb2c, buffer);
  }
  return startup.flowRate;
}


double StepsPerMic(const char *distPermL) {
  double distance;
  double steps;
  if (distPermL == "TEN") {
    distance = 6.0558 / 1000;  //distance for 10 ml syringe is calculated from cylinder with I.D. of 14.5mm and volume of 1000 mm3.
    steps = distance / stepDistance;
  }
  if (distPermL == "TWENTY") {
    distance = 3.4792 / 1000;  //distance for 10 ml syringe is calculated from cylinder with I.D. of 19.13mm and volume of 1000 mm3.
    steps = distance / stepDistance;
  }
  return steps;
}

void encoderLimit(int min, int max) {
  if (encoderPos < min) { encoderPos = min; }
  if (encoderPos > max) { encoderPos = max; }
}

void selectTrigger() {
  const char *triggerMenu[] = { "No", "Yes" };
  encoderPos = 0;
  int position;
  while (digitalRead(enSW)) {
    encoderLimit(0, 1);
    position = encoderPos;
    listBox(89, 87, 70, 14, ST77XX_BLACK);
    printWords(9, 1, 90, 99, ST77XX_WHITE, triggerMenu[position]);
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 90, 99, 0xfb2c, triggerMenu[position]);
    if(position == 0){
      trigger = false;
    }
    if(position == 1){
      trigger = true;
    }
  }
}

void listBox(uint8_t posX, uint8_t posY, uint8_t wide, uint8_t high, uint16_t fontColor) {
  if (box == true) {
    tft.fillRect(posX, posY, wide, high, fontColor);
    box = false;
  }
}

void PumpScreen(uint16_t color, const char *state) {
  tft.drawRect(2, 108, 158, 20, color);
  printWords(7, 1, 6, 122, color, state);
  printWords(7, 1, 2, 16, ST77XX_WHITE, "Volume");
  printWords(7, 1, 96, 16, ST77XX_WHITE, "Rate");
  printWords(8, 1, 2, 76, 0xfb2c, "Sel Rate");
  printWords(8, 1, 2, 94, 0xfb2c, "(uL/min):");
  tft.drawFastHLine(0, 2, 160, ST77XX_WHITE);
  tft.drawFastHLine(0, 60, 160, ST77XX_WHITE);
  tft.drawFastHLine(0, 104, 160, ST77XX_WHITE);
}

void printNumber(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, double num) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  dtostrf(num, 6, 1, number);
  tft.print(number);
}

void printWords(byte font, int fontSize, int posX, int posY, uint16_t fontColor, const char *words) {
  if (font == 9) {
    tft.setFont(&FreeSansBold9pt7b);
  } else if (font == 7) {
    tft.setFont(&FreeSansBold7pt7b);
  } else if (font == 8) {
    tft.setFont(&FreeSansBold8pt7b);
  } else if (font == 0) {
    tft.setFont();
  }
  tft.setTextSize(fontSize);
  tft.setCursor(posX, posY);
  tft.setTextColor(fontColor, ST77XX_BLACK);
  tft.print(words);
}

void stepper(unsigned long delay_us, int direct) {
  // digitalWrite(en, LOW);
  // digitalWrite(m0, HIGH);
  // digitalWrite(m1, LOW);
  current_us = micros();
  if (direct == 1) {
    digitalWrite(dir, LOW);
  }
  if (direct == -1) {
    digitalWrite(dir, HIGH);
  }
  digitalWrite(step, LOW);
  if (current_us - previous_us >= delay_us) {
    digitalWrite(step, HIGH);
    stepCounter++;
    digitalWrite(step, LOW);
    previous_us = current_us;
  }
}

void runPump(float tempRate, int Direction) {
  unsigned long delayTime;
  delayTime = 60000000.000 / ((stepsPerMicroliter * tempRate) * 1.010);
  stepper(delayTime, Direction);
  sprintf(selected, " %4d", startup.flowRate);
}

void math() {
  volPumped = (stepCounter / stepsPerMicroliter);
  actualRate = (volPumped) / ((timeDiff / 1000.00) / 60.00);
  actualVolume = startup.syringeVol - (volPumped / 1000.00);
  startup.syringeVol = actualVolume;
  
}

// /******************************** Core Functions ********************************/

void isRunning() {
int trigState;
  if (UseStartTime == true) {
    startMillis = millis();
    // encoderPos = startup.flowRate;
    UseStartTime = false;
  }
  if (trigger == true) {
    trigState = digitalRead(extTrigger);
    if (trigState == LOW) {
      tft.fillScreen(ST77XX_BLACK);
      runState = 2;
      encoderPos = 0;
    }
  }
  runPump(startup.flowRate, -1);
  currentMillis = millis() - startMillis;
  timeDiff = (currentMillis - previousMillis);
  if (timeDiff >= 1000) {
    math();
    // currentTime = (currentMillis / 1000.00);
    sprintf(volume, "%.2f ", actualVolume);
    sprintf(rate, "%.2f ", actualRate);
    printWords(0, 2, 2, 24, ST77XX_CYAN, volume);
    printWords(0, 2, 74, 24, ST77XX_CYAN, rate);
    // sprintf(diagnostic, "%.2f, %d, %.2f, %.2f, %.2f, %d", volPumped, stepCounter, stepsPerMicroliter, actualVolume, actualRate, timeDiff);
    // Serial.println(diagnostic);
    stepCounter = 0;
    if (actualVolume <= 0.1) {
      tft.fillScreen(ST77XX_BLACK);
      runState = 2;
    }
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST77XX_BLACK);
    runState = 2;
    encoderPos = 0;
  }
}

void isStopping() {
  const char *stopMenu[] = { "START","CHANGE", "PURGE", "FILL", "RESET?" };
  encoderLimit(0, 4);
  listBox(77, 109, 82, 18, ST77XX_BLACK);
  printWords(7, 1, 78, 122, ST77XX_YELLOW, stopMenu[encoderPos]);
  sprintf(selected, " %3d", startup.flowRate);
  sprintf(volume, "%.2f ", startup.syringeVol);
  printWords(0, 2, 2, 24, ST77XX_CYAN, volume);
  printWords(0, 3, 74, 68, ST77XX_RED, selected);
  PumpScreen(ST77XX_RED, "STOPPED");
  int trigState;
  if (trigger == true) {
    trigState = digitalRead(extTrigger);
    if (trigState == HIGH) {
      runState = 0;
      tft.fillScreen(ST7735_BLACK);
      PumpScreen(ST77XX_GREEN, "RUNNING");
      printWords(0, 3, 74, 68, ST77XX_RED, selected);
      printWords(7, 1, 78, 122, ST77XX_YELLOW, "STOP");
      UseStartTime = true;
    }
  }
  while (digitalRead(enSW) == 0) {
    int switchChoice = encoderPos;
    if (switchChoice == 0) {
      runState = 0;
      tft.fillScreen(ST7735_BLACK);
      PumpScreen(ST77XX_GREEN, "RUNNING");
      printWords(0, 3, 74, 68, ST77XX_RED, selected);
      printWords(7, 1, 78, 122, ST77XX_YELLOW, "STOP");
      UseStartTime = true;
    }
    else if (switchChoice == 1) {
    tft.fillScreen(ST7735_BLACK);
    PumpScreen(ST77XX_BLUE, "CHANGE");
    runState = 1;
    }
    else if (switchChoice == 2) {
    tft.fillScreen(ST7735_BLACK);
    PumpScreen(ST77XX_MAGENTA, "PURGE");
    printWords(0, 3, 74, 68, ST77XX_MAGENTA, "2000");
    runState = 3;
    }
    else if (switchChoice == 3) {
    tft.fillScreen(ST7735_BLACK);
    PumpScreen(ST77XX_ORANGE, "FILL");
    printWords(0, 3, 74, 68, ST77XX_ORANGE, "2000");
    runState = 4;
    }
    else if (switchChoice == 4) {
      initialize.write(startup);
      delay(200);
      NVIC_SystemReset();
    }
  }
}

int isChanging() {
  encoderPos = startup.flowRate;
  printWords(7, 1, 78, 122, ST77XX_YELLOW, "SELECT");
  while (digitalRead(enSW)) {
    encoderLimit(0, 1000); //put back to 1000 when you get rid of the 10 multiplier!
    startup.flowRate = encoderPos;
    sprintf(selected, " %3d", startup.flowRate);
    printWords(0, 3, 74, 68, ST77XX_BLUE, selected);
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST7735_BLACK);
    runState = 2;
    encoderPos = -1;
  }
  return startup.flowRate;
}

void isPurging() {
  runPump(2000, -1);
  currentMillis = millis();
  timeDiff = (currentMillis - previousMillis);
  if (timeDiff >= 1000) {
    math();
    printWords(7, 1, 78, 122, ST77XX_YELLOW, "STOP");
    sprintf(volume, "%.2f ", actualVolume);
    printWords(0, 2, 2, 24, ST77XX_CYAN, volume);
    startup.syringeVol = actualVolume;
    if (actualVolume <= 0.1) {
      tft.fillScreen(ST7735_BLACK);
      runState = 2;
    }
    stepCounter = 0;
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST7735_BLACK);
    runState = 2;
    encoderPos = -1;
  }
}

void isFilling() {
  runPump(10000, 1);
  currentMillis = millis();
  if (currentMillis - previousMillis >= 1000) {
    timeDiff = (currentMillis - previousMillis);
    volPumped = (stepCounter / stepsPerMicroliter);
    actualVolume = startup.syringeVol + (volPumped / 1000.00);
    printWords(7, 1, 78, 122, ST77XX_YELLOW, "STOP");
    sprintf(volume, "%.2f ", actualVolume);
    printWords(0, 2, 2, 24, ST77XX_CYAN, volume);
    startup.syringeVol = actualVolume;
    if (syringeName == "TEN" && actualVolume >= 10.01) {
      tft.fillScreen(ST7735_BLACK);
      runState = 2;
    }
    else if (syringeName == "TWENTY" && actualVolume >= 20.01) {
      tft.fillScreen(ST7735_BLACK);
      runState = 2;
    }
    stepCounter = 0;
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST7735_BLACK);
    runState = 2;
    encoderPos = -1;
  }
}