/***************************************************
 *   ITSY BITSY M4 SAMD51 WITH CUSTOM BOARD CP1.   *
 *      1.8" LCD TFT ST7735 DISPLAY 128X160.       *
 *             REVISED 13MAY2025 NRT               *
 *    THIS TRIGGERS PUMP. IT DOES NOT RUN PUMP!    *
 ***************************************************/

#include <Wire.h>
#include "ads.h"
#include "bitmaps.h"
#include "FlashStorage.h"
#include "avr/dtostrf.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include "FreeSansBold7pt7b.h"
#include "FreeSansBold8pt7b.h"
#include "FreeSansBold9pt7b.h"
#include <Adafruit_ST7735.h>      // Hardware-specific library

/*ADC Setup*/
ADS1115 ads;
byte calibrationOrder;

/*TFT Setup*/
#define TFT_CS    A4
#define TFT_DC    A3
#define TFT_RST  -1   // Or set to -1 and connect to Arduino RESET pin
Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

/*Rotary Encoder Setup and interrups*/
#define pinDC 10
#define pinCS 11
#define enSW 12
volatile byte aFlag = 0;    //  let's us know when we're expecting a rising edge on pinDC to signal that the encoder has arrived at a detent
volatile byte bFlag = 0;    //  let's us know when we're expecting a rising edge on pinCS to signal that the encoder has arrived at a detent (opposite direction to when aFlag is set)
int encoderPos;             //  this variable stores our current value of encoder position. Change to int or uin16_t instead of byte if you want to record a larger range than 0-255
int bigPos;                 //bigger increment of encoder position
volatile uint32_t reading = 0;  //  somewhere to store the direct values we read from our interrupt pins before checking to see if we have moved a whole detent
uint32_t maskA;
uint32_t maskB;
uint32_t maskAB;
volatile uint32_t *port;
bool box;
bool approve;
int runState = 0;
int choice;
int count;

/*Pump Trigger Setup*/
#define PumpTrig 3

void fPinDC() {
  noInterrupts();
  reading = *port & maskAB;
  if ((reading == maskAB) && aFlag) {              //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos --;
    bigPos = encoderPos * 5; 
    approve = !approve;                            //decrement the encoder's position count
    box = !box;    
    bFlag = 0;                                     //reset flags for the next turn
    aFlag = 0;                                     //reset flags for the next turn
  }
  else if (reading == maskB) bFlag = 1;
  interrupts();                                   //signal that we're expecting pinCS to signal the transition to detent from free rotation
}
void fPinCS() {
  noInterrupts();
  reading = *port & maskAB;
  if (reading == maskAB && bFlag) {               //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos ++;
    bigPos = encoderPos * 5;                      //increment the encoder's position count
    approve = !approve;
    box = !box;
    bFlag = 0;                                    //reset flags for the next turn
    aFlag = 0;                                    //reset flags for the next turn
  }
  else if (reading == maskA) aFlag = 1;
  interrupts();                                   //signal that we're expecting pinDC to signal the transition to detent from free rotation
}

/*Lighting Pins and camera*/
#define CamTrig 13     //attach + to J13 jumper and - to GND.
#define redPin A2         //attach + to JA2 jumper and - to GND.
#define bluePin 1        //attach + to JA5 jumper and - to GND.
#define whitePin A5        //attach + to J1  jumper and - to GND.
char lights;
static int interval = 5;         //time for the camera to trigger high

/*Pressure sensor calibration an setup*/
int txdx1 = 0;                      //identity of first transducer
int iMinP = 0;                      // Raw value calibration lower point
int iMaxP = 65535;                  // Raw value calibration upper point
double oMinP = 0.00;                // Pressure calibration lower point
double oMaxP = 200.00;              // Pressure calibration upper point. This is in mmHg. This is about the max it can do.
double PRESSURE_CAL_MIN = 0.00;
double PRESSURE_CAL_MAX = 60.0;

struct cal_matrix {
  bool valid;
  double pLowSel;
  double pHiSel;
  int pLowADC;
  int pHiADC;
} calib;

struct init_matrix {
  bool saved;
  int timeDelay;         //the time delay between frames.
  int numSamples;        //the number of samples averaged.
} startup;

/*Initialize Flash Storage*/
FlashStorage(calibrate, cal_matrix);
FlashStorage(initialize, init_matrix);

/*Miscellaneous global variables*/
unsigned long previousMillis = 0;        // Resetting the clock to determine how much time has elapsed.
unsigned long currentMillis;
unsigned long startMillis;
double avgPressure = 0.0;
char number[8];
char frameCount[6];
char pressure[6];
char time[12];
char selected[4];
char rate[6];
char volume[4];
char diagnostic[32];
double avg;
double currentTime;
bool UseStartTime = true;

void setup() {
  Serial.begin(115200);
  ads.begin();
  ads.setGain(GAIN_ONE);
  pinMode(enSW, INPUT_PULLUP);
  pinMode(redPin, OUTPUT);
  pinMode(bluePin, OUTPUT);
  pinMode(whitePin, OUTPUT);
  pinMode(CamTrig, OUTPUT);
  pinMode(PumpTrig, OUTPUT);
  digitalWrite(CamTrig, LOW);
  digitalWrite(redPin, LOW);
  digitalWrite(bluePin, LOW);
  digitalWrite(whitePin, LOW);
  digitalWrite(PumpTrig, LOW);
  pinMode(pinDC, INPUT_PULLUP);
  pinMode(pinCS, INPUT_PULLUP);
  attachInterrupt(pinDC, fPinDC, CHANGE);     //Sets interrupt for rotary encoder so that it works with above functions;
  attachInterrupt(pinCS, fPinCS, CHANGE);     //RISING for old RE; CHANGE for blue one. 
  maskA = digitalPinToBitMask(pinDC);
  maskB = digitalPinToBitMask(pinCS);
  maskAB = maskA | maskB;
  port = portInputRegister(digitalPinToPort(pinDC));
  delay(1000);
  tft.initR(INITR_GREENTAB);
  tft.initR(INITR_BLACKTAB);
  tft.fillScreen(ST7735_BLACK);
  tft.setRotation(1);
  tft.setTextWrap(false);
 
  bootup();
  calibration();
  lighting();
  delay(500);
  timeDelaySelect();
  initialize.write(startup);
  delay(500);
  clickBegin();
  delay(500);
}

void loop() {
  if (runState == 0) {
    isStopping();
  }
  else if (runState == 1) {
    
    isRunning();
  }
}
/*******************************Utility Functions *******************************/
void averagingPressure() {
  double pressureAvg;
  double sample[startup.numSamples];
  double avgSample;
  uint8_t i;
  for (i = 0; i < startup.numSamples; i++) {
    sample[i] = ads.measure(txdx1);
  }
  avgSample = 0;
  for (i = 0; i < startup.numSamples; i++) {
    avgSample += sample[i];
  }
  avgSample /= startup.numSamples;
  avg = avgSample;
}

void bootup () {
  int h = 128, w = 160, row, col, buffidx = 0;
  for (row = 0; row < h; row++) {
    for (col = 0; col < w; col++) {
      tft.drawPixel(col, row, pgm_read_word(logo + buffidx));
      buffidx++;
    }
  }
  printWords(0, 1, 120, 117, ST77XX_RED, "v3.01");
  startup = initialize.read();
  startup.numSamples = 10;
  if (startup.saved == false) {
    startup.timeDelay = 100;
  }
  while (digitalRead(enSW)){ 
  }
  while (digitalRead(enSW) == 0) {
    startup.saved = true;
    tft.fillScreen(ST77XX_BLACK);
  }
}

void calibration() {
  const char *calMenu[] = { "Load", "New", "Debug" };
  encoderPos = 0;
  initScreen();
  while (digitalRead(enSW)) {
    encoderLimit(0, 2);
    listBox(79, 31, 81, 19, ST77XX_BLACK);
    printWords(9, 1, 80, 45, ST77XX_WHITE, calMenu[encoderPos]);
    choice = encoderPos;
  } 
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 45, 0xfb2c, calMenu[choice]);
  }
  if (choice == 0) {
    calib = calibrate.read();
    if (calib.valid == true) {
      calWords();
      calNums();
      delay(100);
      offsetPressure();
      tft.fillScreen(ST77XX_BLACK);
      initScreen();
      printWords(9, 1, 80, 45, 0xfb2c, "Done");
      calibrate.write(calib);
      delay(250);
    }
    else {
      calibration();
    }
  }
  if (choice == 1) {
    delay(250);
    calWords();
    PressureADCLow();
    PressureSelLow();
    PressureADCHigh();
    PressureSelHigh();
    offsetPressure();
    calib.valid = true;
    calibrate.write(calib);
    tft.fillScreen(ST77XX_BLACK);
    initScreen();
    printWords(9, 1, 80, 45, 0xfb2c, "Done");
    delay(250);
  }
  if (choice == 2) {
    tft.fillScreen(ST77XX_BLACK);
    calib.pLowADC = 372;
    calib.pLowSel = 0;
    calib.pHiADC =  8681;
    calib.pHiSel = 80;
    calWords();
    calNums();
    offsetPressure();
    tft.fillScreen(ST77XX_BLACK);
    initScreen();
    calib.valid = true;
    calibrate.write(calib);
    printWords(9, 1, 80, 45, 0xfb2c, "Done");
    delay(250);
  }
}

void calNums() {
  printCalNumber(2, 90, 26, ST77XX_WHITE, ST77XX_BLACK, calib.pLowADC, 6);
  printCalNumber(2, 90, 46, ST77XX_WHITE, ST77XX_BLACK, calib.pLowSel, 6);
  printCalNumber(2, 90, 66, ST77XX_WHITE, ST77XX_BLACK, calib.pHiADC, 6);
  printCalNumber(2, 90, 86, ST77XX_WHITE, ST77XX_BLACK, calib.pHiSel, 6);
}

void calWords() {
  tft.fillScreen(ST77XX_BLACK);
  printWords(9, 0, 2, 19, 0x64df, "Calibrate Pressure");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Min ADC:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 59, 0x04d3, "Sel Min:");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "Max ADC:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  printWords(9, 1, 2, 99, 0x04d3, "Sel Max:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
  printWords(9, 1, 2, 119, 0x04d3, "Offset:");
}

void clickBegin () {
  printWords(8, 1, 30, 121, 0x64df, "Click to Begin");
  ads.linearCal(calib.pLowADC, calib.pHiADC, calib.pLowSel, calib.pHiSel);
  while (digitalRead(enSW)) { }
  while (digitalRead(enSW) == 0) {
    encoderPos = 0;
    startMillis = millis();
    tft.fillScreen(ST7735_BLACK);
  }
}

void encoderLimit(int min, int max) {
  if (encoderPos < min) { encoderPos = min; }
  if (encoderPos > max) { encoderPos = max; }
}

void hiLow(){
  int now = interval;
  while (now--) { 
    digitalWrite(CamTrig, HIGH);
  }
    digitalWrite(CamTrig, LOW);
}

void initScreen() {
  printWords(9, 1, 30, 19, 0x64df, "Initialization");
  tft.drawFastHLine(2, 25, 158, 0xfe31);
  printWords(9, 1, 2, 45, 0x04d3, "Calib:");
  tft.drawFastHLine(2, 52, 158, 0xfe31);
  printWords(9, 1, 2, 72, 0x04d3, "Lights:");
  tft.drawFastHLine(2, 79, 158, 0xfe31);
  printWords(9, 1, 2, 99, 0x04d3, "Delay:");
  tft.drawFastHLine(2, 106, 158, 0xfe31);
}

void lighting() {
  const char *myString[] = {"White", "Blue", "Red", "All", "None"};
  encoderPos = 0;
    while (digitalRead(enSW)) {
      int colorChoice = encoderPos;
      encoderLimit(0, 4);
      listBox(80, 58, 80, 16, ST77XX_BLACK);
      printWords(9, 1, 80, 72, ST77XX_WHITE, myString[colorChoice]);
      if (colorChoice == 0) {
        digitalWrite(redPin, LOW); digitalWrite(whitePin, HIGH); digitalWrite(bluePin, LOW);
        choice = colorChoice;
      }
      else if (colorChoice == 1) {
        digitalWrite(bluePin, HIGH); digitalWrite(whitePin, LOW); digitalWrite(redPin, LOW);
        choice = colorChoice;
      }
      else if (colorChoice == 2) {
        digitalWrite(redPin, HIGH); digitalWrite(whitePin, LOW); digitalWrite(bluePin, LOW);
        choice = colorChoice;
      }
      else if (colorChoice == 3) {
        digitalWrite(redPin, HIGH); digitalWrite(bluePin, HIGH); digitalWrite(whitePin, HIGH);
        choice = colorChoice;
      }
      else if (colorChoice == 4) {
        digitalWrite(redPin, LOW); digitalWrite(bluePin, LOW); digitalWrite(whitePin, LOW);
        choice = colorChoice;
      }
    }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 72, 0xfb2c, myString[choice]);
  }
}

void listBox(uint8_t posX, uint8_t posY, uint8_t wide, uint8_t high, uint16_t fontColor) {
  if (box == true) {
    tft.fillRect(posX, posY, wide, high, fontColor);
    box = false;
  }
}

void offsetPressure() {
  startup.numSamples = 11;
  double samplesOffset[startup.numSamples];
  double avgSample;
  uint8_t i;
  double tempAvg;
  encoderPos = 0;
  int tempLowADC = calib.pLowADC;
  int tempHighADC = calib.pHiADC;
  while (digitalRead(enSW)) {
    tempLowADC = (calib.pLowADC - (encoderPos * 10));
    tempHighADC = (calib.pHiADC - (encoderPos * 10));
    for (i = 0; i < startup.numSamples; i++) {
      ads.linearCal(tempLowADC, tempHighADC, calib.pLowSel, calib.pHiSel);
      samplesOffset[i] = ads.measure(txdx1);
      delay(10);
    }
    avgSample = 0;
    for (i = 0; i < startup.numSamples; i++) {
      avgSample += samplesOffset[i];
    }
    avgSample /= startup.numSamples;
    tempAvg = avgSample;
    char tempOffset[10];
    sprintf(tempOffset, "%.1f ", tempAvg);
    printWords(0, 2, 102, 106, ST77XX_WHITE, tempOffset);
  }
  while (digitalRead(enSW) == 0) {
    calib.pLowADC = tempLowADC;
    calib.pHiADC = tempHighADC;
    delay(250);
  }
}

void PressureADCHigh() {
  int firstADC = 0;
  int avgHigh;
  uint8_t i;
  int samplesHigh[startup.numSamples];
  while (digitalRead(enSW)) {
    for (i = 0; i < startup.numSamples; i++) {
      samplesHigh[i] = ads.readADC_Differential_0_1();
      delay(1);
    }
    avgHigh = 0;
    for (i = 0; i < startup.numSamples; i++) {
      avgHigh += samplesHigh[i];
    }
    avgHigh /= startup.numSamples;
    firstADC = avgHigh;
    char buffer[10];
    sprintf(buffer, "%d ", firstADC);
    printWords(0, 2, 90, 66, ST77XX_WHITE, buffer);
    delay(200);
  }
  while (digitalRead(enSW) == 0) {
    calib.pHiADC = firstADC;
    delay(100);
  }
}

void PressureADCLow() {
  calWords();
  int firstADC;
  int avgLow;
  uint8_t i;
  int samplesLow[startup.numSamples];
  while (digitalRead(enSW)) {
    for (i = 0; i < startup.numSamples; i++) {
      samplesLow[i] = ads.readADC_Differential_0_1();
      delay(1);
    }
    avgLow = 0;
    for (i = 0; i < startup.numSamples; i++) {
      avgLow += samplesLow[i];
    }
    avgLow /= startup.numSamples;
    firstADC = avgLow;
    char buffer[10];
    sprintf(buffer, "%d ", firstADC);
    printWords(0, 2, 90, 26, ST77XX_WHITE, buffer);
    delay(200);
  }
  while (digitalRead(enSW) == 0) {
    calib.pLowADC = firstADC;
    delay(100);
  }
}

void PressureSelHigh() {
  encoderPos = PRESSURE_CAL_MAX;
  while (digitalRead(enSW)) {
    char buffer[10];
    sprintf(buffer, "%d ", encoderPos);
    printWords(0, 2, 90, 86, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
  }
  calib.pHiSel = encoderPos;
  delay(100);
}

void PressureSelLow() {
  encoderPos = PRESSURE_CAL_MIN;
  while (digitalRead(enSW)) {
    char buffer[10]; 
    sprintf(buffer, "%d ", encoderPos);
    printWords(0, 2, 90, 46, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    calib.pLowSel = encoderPos;
    delay(100);
  }
}

void printWords(byte font, int fontSize, int posX, int posY, uint16_t fontColor, const char* words) {
  if (font == 9) {
    tft.setFont(&FreeSansBold9pt7b);
  }
  else if (font == 7) {
    tft.setFont(&FreeSansBold7pt7b);
  }
  else if (font == 8) {
    tft.setFont(&FreeSansBold8pt7b);
  }
  else if (font == 0) {
    tft.setFont();
  }
  tft.setTextSize(fontSize);
  tft.setCursor(posX, posY);
  tft.setTextColor(fontColor, ST77XX_BLACK);
  tft.print(words);
}
void printNumber(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, double num) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  dtostrf(num, 6, 1, number);
  tft.print(number);
}
void printCalNumber(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, double num, int width) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  dtostrf(num, width, 0, number);
  tft.print(number);
}
void printInt(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, int num) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  tft.print(num);
}
void printPressure(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, double num) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  dtostrf(num, 3, 0, pressure);
  tft.print(pressure);
}

void runScreen(uint16_t color, const char *state) {
  printWords(9, 1, 2, 19, 0x64df, "Pressure");
  tft.drawFastHLine(2, 25, 158, 0xfe31);
  printWords(9, 1, 2, 44, 0x64df, "Frame");
  tft.drawFastHLine(2, 52, 158, 0xfe31);
  printWords(9, 1, 2, 70, 0x64df, "Time");
  tft.drawFastHLine(2, 78, 158, 0xfe31);
  // printWords(9, 1, 2, 96, 0x64df, "uL/min");
  tft.drawRect(2, 108, 158, 20, color);
  printWords(7, 1, 6, 122, color, state);
}

void timeDelaySelect() {
  int selTime;
  char buffer[5];
  bigPos = 0;
  if (startup.timeDelay > 1000) {
    startup.timeDelay = 1000;
  }
  while (digitalRead(enSW)) {
    selTime = startup.timeDelay + bigPos;
      if (selTime < 0){
        selTime = 0;
        encoderPos = 0;
      }    
    sprintf(buffer, "%d  ", selTime);
    printWords(0, 2, 82, 86, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 82, 86, 0xfb2c, buffer);
    startup.timeDelay = selTime;
  }
}

/*******************************Core Functions *******************************/
void isRunning() {
  if (UseStartTime == true) {
    startMillis = millis();
    previousMillis = startMillis;
    UseStartTime = false;
  }
  currentMillis = millis() - startMillis;
    if (currentMillis - previousMillis  >= startup.timeDelay) {
    currentTime = (currentMillis / 1000.00);
    hiLow();
    count++;
    averagingPressure();
    dtostrf(avg, 5, 2, pressure);
    dtostrf(count, 5, 0, frameCount);
    dtostrf(currentTime, 8, 2, time);
    printWords(0, 2, 100, 6, ST77XX_WHITE, pressure);
    printWords(0, 2, 100, 31, ST77XX_WHITE, frameCount);
    printWords(0, 2, 64, 56, ST77XX_WHITE, time);
    Serial.print(count);
    Serial.print(", ");
    Serial.print(currentTime);
    Serial.print(", ");
    Serial.println(avg);
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    runState = 0;
    encoderPos = 0;
    digitalWrite(PumpTrig, LOW);
    tft.fillScreen(ST77XX_BLACK);
  }
}

void isStopping() {
  const char *stopMenu[] = { "UNPAUSE", "ZERO?", "RESET?" };
  runScreen(ST77XX_RED, "STOPPED");
  currentMillis  = millis() - startMillis;
  encoderLimit(0, 2);
  listBox(79, 109, 79, 18, ST77XX_BLACK);
  printWords(7, 1, 82, 122, ST77XX_YELLOW, stopMenu[encoderPos]);
    if (currentMillis - previousMillis >= startup.timeDelay) {
      averagingPressure();
      dtostrf(avg, 5, 2, pressure);
      dtostrf(count, 5, 0, frameCount);
      printWords(0, 2, 100, 6, ST77XX_RED, pressure);
      printWords(0, 2, 100, 31, ST77XX_RED, frameCount);
      printWords(0, 2, 124, 57, ST77XX_RED, "---");
      previousMillis = currentMillis;
    }
  while (digitalRead(enSW) == 0) {
    int switchChoice = encoderPos;
    if (switchChoice == 0) {
      runState = 1;
      digitalWrite(PumpTrig, HIGH);
      tft.fillScreen(ST7735_BLACK);
      runScreen(ST77XX_GREEN, "RUNNING");
    }
    else if (switchChoice == 1) {
      count = 0;
      UseStartTime = true;
      runState = 0;
    }
    else if (switchChoice == 2) {
      initialize.write(startup);
      delay(200);
      NVIC_SystemReset();
    }
  }
}
