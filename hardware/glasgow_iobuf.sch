EESchema Schematic File Version 4
LIBS:glasgow-cache
EELAYER 26 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 2 3
Title "I/O Buffer"
Date ""
Rev "A"
Comp "whitequark research"
Comment1 "Glasgow Debug Tool"
Comment2 ""
Comment3 ""
Comment4 ""
$EndDescr
$Comp
L Glasgow-JTAG:FXMA108BQX U5
U 1 1 5AF87C59
P 5300 3650
AR Path="/5AF7D604/5AF87C59" Ref="U5"  Part="1" 
AR Path="/5AFBDC9E/5AF87C59" Ref="U6"  Part="1" 
F 0 "U6" H 5050 4300 50  0000 C CNN
F 1 "FXMA108BQX" H 5700 4300 50  0000 C CNN
F 2 "Package_DFN_QFN:WQFN-20-1EP_2.5x4.5mm_P0.5mm_EP1x2.9mm" H 6900 4050 50  0001 C CNN
F 3 "http://www.onsemi.com/PowerSolutions/product.do?id=FXMA108" H 5300 3700 50  0001 C CNN
F 4 "512-FXMA108BQX" H 5300 3650 50  0001 C CNN "Mouser_PN"
	1    5300 3650
	1    0    0    -1  
$EndComp
$Comp
L power:GND #PWR0101
U 1 1 5AF87D7F
P 5300 4400
AR Path="/5AF7D604/5AF87D7F" Ref="#PWR0101"  Part="1" 
AR Path="/5AFBDC9E/5AF87D7F" Ref="#PWR0104"  Part="1" 
F 0 "#PWR0104" H 5300 4150 50  0001 C CNN
F 1 "GND" H 5305 4227 50  0000 C CNN
F 2 "" H 5300 4400 50  0001 C CNN
F 3 "" H 5300 4400 50  0001 C CNN
	1    5300 4400
	1    0    0    -1  
$EndComp
Wire Wire Line
	5300 4350 5300 4400
$Comp
L power:+3.3V #PWR0102
U 1 1 5AF87E10
P 5200 2900
AR Path="/5AF7D604/5AF87E10" Ref="#PWR0102"  Part="1" 
AR Path="/5AFBDC9E/5AF87E10" Ref="#PWR0105"  Part="1" 
F 0 "#PWR0105" H 5200 2750 50  0001 C CNN
F 1 "+3.3V" H 5215 3073 50  0000 C CNN
F 2 "" H 5200 2900 50  0001 C CNN
F 3 "" H 5200 2900 50  0001 C CNN
	1    5200 2900
	1    0    0    -1  
$EndComp
Wire Wire Line
	5200 2900 5200 2950
Wire Wire Line
	4850 3250 4900 3250
Wire Wire Line
	4850 3350 4900 3350
Wire Wire Line
	4850 3450 4900 3450
Wire Wire Line
	4850 3550 4900 3550
Wire Wire Line
	4850 3650 4900 3650
Wire Wire Line
	4850 3750 4900 3750
Wire Wire Line
	4850 3850 4900 3850
Wire Wire Line
	4850 3950 4900 3950
Wire Wire Line
	4850 4050 4900 4050
Wire Wire Line
	5700 3350 6400 3350
Wire Wire Line
	5700 3450 6400 3450
Wire Wire Line
	5700 3550 6400 3550
Wire Wire Line
	5700 3650 6400 3650
Wire Wire Line
	5700 3750 6400 3750
Wire Wire Line
	5700 3850 6400 3850
Wire Wire Line
	5700 3950 6400 3950
Wire Wire Line
	5700 4050 6400 4050
Wire Wire Line
	6950 3350 6900 3350
Wire Wire Line
	6950 3450 6900 3450
Wire Wire Line
	6950 3550 6900 3550
Wire Wire Line
	6950 3650 6900 3650
Wire Wire Line
	6950 3750 6900 3750
Wire Wire Line
	6950 3850 6900 3850
Wire Wire Line
	6950 3950 6900 3950
Wire Wire Line
	6950 4050 6900 4050
Wire Wire Line
	6950 4150 6900 4150
$Comp
L power:GND #PWR0103
U 1 1 5AF8878D
P 6950 4200
AR Path="/5AF7D604/5AF8878D" Ref="#PWR0103"  Part="1" 
AR Path="/5AFBDC9E/5AF8878D" Ref="#PWR0106"  Part="1" 
F 0 "#PWR0106" H 6950 3950 50  0001 C CNN
F 1 "GND" H 6955 4027 50  0000 C CNN
F 2 "" H 6950 4200 50  0001 C CNN
F 3 "" H 6950 4200 50  0001 C CNN
	1    6950 4200
	1    0    0    -1  
$EndComp
Wire Wire Line
	6950 4200 6950 4150
Connection ~ 6950 3450
Wire Wire Line
	6950 3450 6950 3350
Connection ~ 6950 3550
Wire Wire Line
	6950 3550 6950 3450
Connection ~ 6950 3650
Wire Wire Line
	6950 3650 6950 3550
Connection ~ 6950 3750
Wire Wire Line
	6950 3750 6950 3650
Connection ~ 6950 3850
Wire Wire Line
	6950 3850 6950 3750
Connection ~ 6950 3950
Wire Wire Line
	6950 3950 6950 3850
Connection ~ 6950 4050
Wire Wire Line
	6950 4050 6950 3950
Connection ~ 6950 4150
Wire Wire Line
	6950 4150 6950 4050
Wire Wire Line
	6900 3250 6950 3250
Wire Wire Line
	6950 3250 6950 3150
Wire Wire Line
	6950 3150 6350 3150
Wire Wire Line
	6350 3150 6350 3250
Wire Wire Line
	6350 3250 6400 3250
Text HLabel 4850 3350 0    50   Input ~ 0
Q0
Text HLabel 4850 3450 0    50   Input ~ 0
Q1
Text HLabel 4850 3550 0    50   Input ~ 0
Q2
Text HLabel 4850 3650 0    50   Input ~ 0
Q3
Text HLabel 4850 3750 0    50   Input ~ 0
Q4
Text HLabel 4850 3850 0    50   Input ~ 0
Q5
Text HLabel 4850 3950 0    50   Input ~ 0
Q6
Text HLabel 4850 4050 0    50   Input ~ 0
Q7
Text HLabel 4850 3250 0    50   Input ~ 0
OE
Wire Wire Line
	5400 2950 5400 2900
Wire Wire Line
	5400 2900 6350 2900
Wire Wire Line
	6350 2900 6350 3150
Connection ~ 6350 3150
Text Label 6450 3150 0    50   ~ 0
VTG
$Comp
L Connector_Generic:Conn_02x10_Odd_Even J2
U 1 1 5AFC7F21
P 6600 3650
AR Path="/5AF7D604/5AFC7F21" Ref="J2"  Part="1" 
AR Path="/5AFBDC9E/5AFC7F21" Ref="J3"  Part="1" 
F 0 "J3" H 6650 3050 50  0000 C CNN
F 1 "Conn_02x10_Odd_Even" H 6650 4176 50  0001 C CNN
F 2 "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical" H 6600 3650 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/276/0878342019_PCB_HEADERS-152849.pdf" H 6600 3650 50  0001 C CNN
F 4 "538-87834-2019" H 6600 3650 50  0001 C CNN "Mouser_PN"
	1    6600 3650
	1    0    0    -1  
$EndComp
Text Label 5750 3350 0    50   ~ 0
Y0
Text Label 5750 3450 0    50   ~ 0
Y1
Text Label 5750 3550 0    50   ~ 0
Y2
Text Label 5750 3650 0    50   ~ 0
Y3
Text Label 5750 3750 0    50   ~ 0
Y4
Text Label 5750 3850 0    50   ~ 0
Y5
Text Label 5750 3950 0    50   ~ 0
Y6
Text Label 5750 4050 0    50   ~ 0
Y7
NoConn ~ 6400 4150
Text HLabel 3850 3250 0    50   Input ~ 0
SDA
Text HLabel 3850 3350 0    50   Input ~ 0
SCL
$EndSCHEMATC
