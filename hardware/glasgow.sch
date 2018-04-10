EESchema Schematic File Version 4
EELAYER 26 0
EELAYER END
$Descr A4 11693 8268
encoding utf-8
Sheet 1 1
Title "Base Board"
Date ""
Rev "A"
Comp "whitequark research"
Comment1 "Glasgow Debug Tool"
Comment2 ""
Comment3 ""
Comment4 ""
$EndDescr
$Comp
L MCU_Cypress:CY7C68013A-56LTX U1
U 1 1 5ACA0321
P 2750 4050
F 0 "U1" H 2200 6000 50  0000 C CNN
F 1 "CY7C68013A-56LTX" H 3250 6000 50  0000 C CNN
F 2 "Package_DFN_QFN:QFN-56-1EP_8x8mm_P0.5mm_EP4.8x5.5mm" H 2700 4150 50  0001 C CNN
F 3 "http://www.cypress.com/file/138911/download" H 2750 4250 50  0001 C CNN
F 4 "727-CY7C68013A56LTXC" H 2750 4050 50  0001 C CNN "Mouser_PN"
	1    2750 4050
	1    0    0    -1  
$EndComp
$Comp
L Connector_Specialized:USB_B_Micro J1
U 1 1 5ACA0820
P 900 4100
F 0 "J1" H 900 4450 50  0000 C CNN
F 1 "USB_B_Micro" V 650 4100 50  0000 C CNN
F 2 "Connector_USB:USB_Micro-B_Molex_47346-0001" H 1050 4050 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/276/0473460001_IO_CONNECTORS-229243.pdf" H 1050 4050 50  0001 C CNN
F 4 "538-47346-0001" H 900 4100 50  0001 C CNN "Mouser_PN"
	1    900  4100
	1    0    0    -1  
$EndComp
$Comp
L power:GND #PWR02
U 1 1 5ACA09A2
P 900 4550
F 0 "#PWR02" H 900 4300 50  0001 C CNN
F 1 "GND" H 905 4377 50  0000 C CNN
F 2 "" H 900 4550 50  0001 C CNN
F 3 "" H 900 4550 50  0001 C CNN
	1    900  4550
	1    0    0    -1  
$EndComp
$Comp
L power:GND #PWR011
U 1 1 5ACA09EE
P 2750 6150
F 0 "#PWR011" H 2750 5900 50  0001 C CNN
F 1 "GND" H 2755 5977 50  0000 C CNN
F 2 "" H 2750 6150 50  0001 C CNN
F 3 "" H 2750 6150 50  0001 C CNN
	1    2750 6150
	1    0    0    -1  
$EndComp
Wire Wire Line
	2550 6050 2550 6100
Wire Wire Line
	2550 6100 2750 6100
Wire Wire Line
	2950 6100 2950 6050
Wire Wire Line
	2750 6050 2750 6100
Connection ~ 2750 6100
Wire Wire Line
	2750 6100 2950 6100
Wire Wire Line
	2750 6100 2750 6150
Wire Wire Line
	900  4500 900  4550
$Comp
L power:+5V #PWR04
U 1 1 5ACA0A58
P 1250 3850
F 0 "#PWR04" H 1250 3700 50  0001 C CNN
F 1 "+5V" H 1265 4023 50  0000 C CNN
F 2 "" H 1250 3850 50  0001 C CNN
F 3 "" H 1250 3850 50  0001 C CNN
	1    1250 3850
	1    0    0    -1  
$EndComp
Wire Wire Line
	1250 3850 1250 3900
$Comp
L power:+3.3V #PWR010
U 1 1 5ACB436E
P 2750 1950
F 0 "#PWR010" H 2750 1800 50  0001 C CNN
F 1 "+3.3V" H 2765 2123 50  0000 C CNN
F 2 "" H 2750 1950 50  0001 C CNN
F 3 "" H 2750 1950 50  0001 C CNN
	1    2750 1950
	1    0    0    -1  
$EndComp
Wire Wire Line
	2750 1950 2750 2000
$Comp
L Device:C C2
U 1 1 5ACB69D3
P 1400 2650
F 0 "C2" V 1250 2650 50  0000 C CNN
F 1 "18p" V 1550 2650 50  0000 C CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 1438 2500 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 1400 2650 50  0001 C CNN
F 4 "77-VJ0603A180JXACBC" H 1400 2650 50  0001 C CNN "Mouser_PN"
	1    1400 2650
	0    1    1    0   
$EndComp
$Comp
L power:GND #PWR03
U 1 1 5ACB6D67
P 1200 3200
F 0 "#PWR03" H 1200 2950 50  0001 C CNN
F 1 "GND" H 1205 3027 50  0000 C CNN
F 2 "" H 1200 3200 50  0001 C CNN
F 3 "" H 1200 3200 50  0001 C CNN
	1    1200 3200
	1    0    0    -1  
$EndComp
Wire Wire Line
	1200 3200 1200 3150
Wire Wire Line
	1200 2650 1250 2650
Wire Wire Line
	1250 3150 1200 3150
Connection ~ 1200 3150
Wire Wire Line
	1200 3150 1200 2900
$Comp
L Device:R R2
U 1 1 5ACB7B47
P 1750 4900
F 0 "R2" H 1680 4854 50  0000 R CNN
F 1 "2k2" H 1680 4945 50  0000 R CNN
F 2 "Resistor_SMD:R_0603_1608Metric_Pad0.84x1.00mm_HandSolder" V 1680 4900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/447/PYu-RC_Group_51_RoHS_L_9-1314892.pdf" H 1750 4900 50  0001 C CNN
F 4 "603-RC0603FR-072K2L" H 1750 4900 50  0001 C CNN "Mouser_PN"
	1    1750 4900
	1    0    0    1   
$EndComp
Wire Wire Line
	1750 5050 1750 5150
Connection ~ 1750 5150
Wire Wire Line
	1750 5150 2050 5150
Connection ~ 1850 5250
Wire Wire Line
	1850 5050 1850 5250
Wire Wire Line
	1850 5250 2050 5250
Wire Wire Line
	1750 4750 1750 4700
Wire Wire Line
	1750 4700 1800 4700
Wire Wire Line
	1850 4700 1850 4750
Wire Wire Line
	1200 3900 1250 3900
$Comp
L power:+3.3V #PWR05
U 1 1 5ACBABAE
P 1800 4650
F 0 "#PWR05" H 1800 4500 50  0001 C CNN
F 1 "+3.3V" H 1815 4823 50  0000 C CNN
F 2 "" H 1800 4650 50  0001 C CNN
F 3 "" H 1800 4650 50  0001 C CNN
	1    1800 4650
	1    0    0    -1  
$EndComp
Wire Wire Line
	2550 2050 2550 2000
Wire Wire Line
	2550 2000 2750 2000
Connection ~ 2750 2000
Wire Wire Line
	2750 2000 2750 2050
Wire Wire Line
	1800 4650 1800 4700
Connection ~ 1800 4700
Wire Wire Line
	1800 4700 1850 4700
Wire Wire Line
	1950 4200 1950 4450
Wire Wire Line
	1950 4450 2050 4450
Wire Wire Line
	2050 4350 2000 4350
Wire Wire Line
	2000 4350 2000 4100
Wire Wire Line
	1500 5150 1750 5150
Wire Wire Line
	1500 5250 1850 5250
Text Label 1500 5150 0    50   ~ 0
SDA
Text Label 1500 5250 0    50   ~ 0
SCL
NoConn ~ 3450 4350
Wire Wire Line
	2350 6050 2350 6100
Wire Wire Line
	2350 6100 2550 6100
Connection ~ 2550 6100
$Comp
L Device:Crystal_GND24 Y1
U 1 1 5ACC4BC0
P 1700 2900
F 0 "Y1" H 1825 3100 50  0000 L CNN
F 1 "24M" H 1825 3025 50  0000 L CNN
F 2 "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm_HandSoldering" H 1700 2900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/741/LFXTAL058124Reel-940455.pdf" H 1700 2900 50  0001 C CNN
F 4 "449-LFXTAL058124REEL" H 1700 2900 50  0001 C CNN "Mouser_PN"
	1    1700 2900
	1    0    0    -1  
$EndComp
Connection ~ 1200 2900
Wire Wire Line
	1200 2900 1200 2650
$Comp
L power:GND #PWR06
U 1 1 5ACCB418
P 1950 3200
F 0 "#PWR06" H 1950 2950 50  0001 C CNN
F 1 "GND" H 1955 3027 50  0000 C CNN
F 2 "" H 1950 3200 50  0001 C CNN
F 3 "" H 1950 3200 50  0001 C CNN
	1    1950 3200
	1    0    0    -1  
$EndComp
Wire Wire Line
	1950 3200 1950 2900
Wire Wire Line
	1550 2650 1700 2650
Wire Wire Line
	1550 3150 1700 3150
Wire Wire Line
	1200 2900 1550 2900
Wire Wire Line
	1850 2900 1950 2900
Wire Wire Line
	1700 2700 1700 2650
Connection ~ 1700 2650
Wire Wire Line
	1700 2650 2050 2650
Wire Wire Line
	1700 3100 1700 3150
Connection ~ 1700 3150
Wire Wire Line
	1700 3150 2050 3150
$Comp
L Device:R R1
U 1 1 5ACCF0F2
P 950 5000
F 0 "R1" H 1020 5046 50  0000 L CNN
F 1 "1M" H 1020 4955 50  0000 L CNN
F 2 "Resistor_SMD:R_0603_1608Metric_Pad0.84x1.00mm_HandSolder" V 880 5000 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/447/PYu-RC_Group_51_RoHS_L_9-1314892.pdf" H 950 5000 50  0001 C CNN
F 4 "603-RC0603FR-071ML" H 950 5000 50  0001 C CNN "Mouser_PN"
	1    950  5000
	1    0    0    -1  
$EndComp
Wire Wire Line
	950  4850 950  4800
Wire Wire Line
	950  4800 800  4800
Wire Wire Line
	650  4800 650  4850
Wire Wire Line
	800  4500 800  4800
Connection ~ 800  4800
Wire Wire Line
	800  4800 650  4800
Wire Wire Line
	650  5150 650  5200
Wire Wire Line
	650  5200 800  5200
Wire Wire Line
	950  5200 950  5150
$Comp
L power:GND #PWR01
U 1 1 5ACD15FA
P 800 5250
F 0 "#PWR01" H 800 5000 50  0001 C CNN
F 1 "GND" H 805 5077 50  0000 C CNN
F 2 "" H 800 5250 50  0001 C CNN
F 3 "" H 800 5250 50  0001 C CNN
	1    800  5250
	1    0    0    -1  
$EndComp
Wire Wire Line
	800  5200 800  5250
Connection ~ 800  5200
Wire Wire Line
	800  5200 950  5200
$Comp
L power:+3.3V #PWR07
U 1 1 5ACD5106
P 2000 3850
F 0 "#PWR07" H 2000 3700 50  0001 C CNN
F 1 "+3.3V" V 2015 3978 50  0000 L CNN
F 2 "" H 2000 3850 50  0001 C CNN
F 3 "" H 2000 3850 50  0001 C CNN
	1    2000 3850
	0    -1   -1   0   
$EndComp
Wire Wire Line
	2000 3850 2050 3850
$Comp
L Device:C C5
U 1 1 5ACD6C50
P 2000 1050
F 0 "C5" H 2115 1096 50  0000 L CNN
F 1 "u1" H 2115 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 2038 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 2000 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 2000 1050 50  0001 C CNN "Mouser_PN"
	1    2000 1050
	1    0    0    -1  
$EndComp
Wire Wire Line
	2000 900  2000 850 
Wire Wire Line
	2000 850  2300 850 
Wire Wire Line
	4100 850  4100 900 
Wire Wire Line
	3800 850  3800 900 
Connection ~ 3800 850 
Wire Wire Line
	3800 850  4100 850 
Wire Wire Line
	3500 850  3500 900 
Connection ~ 3500 850 
Wire Wire Line
	3500 850  3800 850 
Wire Wire Line
	3200 850  3200 900 
Connection ~ 3200 850 
Wire Wire Line
	3200 850  3500 850 
Wire Wire Line
	2900 850  2900 900 
Connection ~ 2900 850 
Wire Wire Line
	2900 850  3200 850 
Wire Wire Line
	2600 850  2600 900 
Connection ~ 2600 850 
Wire Wire Line
	2600 850  2750 850 
Wire Wire Line
	2300 850  2300 900 
Connection ~ 2300 850 
Wire Wire Line
	2300 850  2600 850 
Wire Wire Line
	2000 1200 2000 1250
Wire Wire Line
	2000 1250 2300 1250
Wire Wire Line
	4100 1250 4100 1200
Wire Wire Line
	2300 1200 2300 1250
Connection ~ 2300 1250
Wire Wire Line
	2300 1250 2600 1250
Wire Wire Line
	2600 1200 2600 1250
Connection ~ 2600 1250
Wire Wire Line
	2600 1250 2750 1250
Wire Wire Line
	2900 1200 2900 1250
Connection ~ 2900 1250
Wire Wire Line
	2900 1250 3200 1250
Wire Wire Line
	3200 1200 3200 1250
Connection ~ 3200 1250
Wire Wire Line
	3200 1250 3500 1250
Wire Wire Line
	3500 1200 3500 1250
Connection ~ 3500 1250
Wire Wire Line
	3500 1250 3800 1250
Wire Wire Line
	3800 1200 3800 1250
Connection ~ 3800 1250
Wire Wire Line
	3800 1250 4100 1250
$Comp
L Device:C C4
U 1 1 5ACF0AA9
P 1600 1050
F 0 "C4" H 1715 1096 50  0000 L CNN
F 1 "4u7" H 1715 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 1638 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/400/lcc_commercial_general_en-837201.pdf" H 1600 1050 50  0001 C CNN
F 4 "810-C1608X5R1C475KAC" H 1600 1050 50  0001 C CNN "Mouser_PN"
	1    1600 1050
	1    0    0    -1  
$EndComp
Wire Wire Line
	2000 850  1600 850 
Wire Wire Line
	1600 850  1600 900 
Connection ~ 2000 850 
Wire Wire Line
	2000 1250 1600 1250
Wire Wire Line
	1600 1250 1600 1200
Connection ~ 2000 1250
$Comp
L Device:C C6
U 1 1 5ACF711C
P 2300 1050
F 0 "C6" H 2415 1096 50  0000 L CNN
F 1 "u1" H 2415 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 2338 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 2300 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 2300 1050 50  0001 C CNN "Mouser_PN"
	1    2300 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C7
U 1 1 5ACF7152
P 2600 1050
F 0 "C7" H 2715 1096 50  0000 L CNN
F 1 "u1" H 2715 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 2638 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 2600 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 2600 1050 50  0001 C CNN "Mouser_PN"
	1    2600 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C8
U 1 1 5ACF7188
P 2900 1050
F 0 "C8" H 3015 1096 50  0000 L CNN
F 1 "u1" H 3015 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 2938 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 2900 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 2900 1050 50  0001 C CNN "Mouser_PN"
	1    2900 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C9
U 1 1 5ACF71C9
P 3200 1050
F 0 "C9" H 3315 1096 50  0000 L CNN
F 1 "u1" H 3315 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 3238 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 3200 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 3200 1050 50  0001 C CNN "Mouser_PN"
	1    3200 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C10
U 1 1 5ACF720B
P 3500 1050
F 0 "C10" H 3615 1096 50  0000 L CNN
F 1 "u1" H 3615 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 3538 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 3500 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 3500 1050 50  0001 C CNN "Mouser_PN"
	1    3500 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C11
U 1 1 5ACF7243
P 3800 1050
F 0 "C11" H 3915 1096 50  0000 L CNN
F 1 "u1" H 3915 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 3838 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 3800 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 3800 1050 50  0001 C CNN "Mouser_PN"
	1    3800 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C12
U 1 1 5ACF72A1
P 4100 1050
F 0 "C12" H 4215 1096 50  0000 L CNN
F 1 "u1" H 4215 1005 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 4138 900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 4100 1050 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 4100 1050 50  0001 C CNN "Mouser_PN"
	1    4100 1050
	1    0    0    -1  
$EndComp
$Comp
L Device:C C1
U 1 1 5ACF7322
P 650 5000
F 0 "C1" H 765 5046 50  0000 L CNN
F 1 "u1" H 765 4955 50  0000 L CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 688 4850 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 650 5000 50  0001 C CNN
F 4 "77-VJ0603Y104JXQPBC" H 650 5000 50  0001 C CNN "Mouser_PN"
	1    650  5000
	1    0    0    -1  
$EndComp
$Comp
L power:+3.3V #PWR08
U 1 1 5ACF96C5
P 2750 800
F 0 "#PWR08" H 2750 650 50  0001 C CNN
F 1 "+3.3V" H 2765 973 50  0000 C CNN
F 2 "" H 2750 800 50  0001 C CNN
F 3 "" H 2750 800 50  0001 C CNN
	1    2750 800 
	1    0    0    -1  
$EndComp
Wire Wire Line
	2750 800  2750 850 
Connection ~ 2750 850 
Wire Wire Line
	2750 850  2900 850 
$Comp
L power:GND #PWR09
U 1 1 5ACFB88D
P 2750 1300
F 0 "#PWR09" H 2750 1050 50  0001 C CNN
F 1 "GND" H 2755 1127 50  0000 C CNN
F 2 "" H 2750 1300 50  0001 C CNN
F 3 "" H 2750 1300 50  0001 C CNN
	1    2750 1300
	1    0    0    -1  
$EndComp
Wire Wire Line
	2750 1300 2750 1250
Connection ~ 2750 1250
Wire Wire Line
	2750 1250 2900 1250
$Comp
L Device:C C3
U 1 1 5AD0B949
P 1400 3150
F 0 "C3" V 1250 3150 50  0000 C CNN
F 1 "18p" V 1550 3150 50  0000 C CNN
F 2 "Capacitor_SMD:C_0603_1608Metric_Pad0.84x1.00mm_HandSolder" H 1438 3000 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/427/vjw1bcbascomseries-223529.pdf" H 1400 3150 50  0001 C CNN
F 4 "77-VJ0603A180JXACBC" H 1400 3150 50  0001 C CNN "Mouser_PN"
	1    1400 3150
	0    1    1    0   
$EndComp
Wire Wire Line
	1600 3750 2050 3750
Text Label 1600 3750 0    50   ~ 0
~CY_RESET
Wire Wire Line
	1200 4100 2000 4100
Wire Wire Line
	1200 4200 1950 4200
$Comp
L Device:R R3
U 1 1 5AD252CA
P 1850 4900
F 0 "R3" H 1780 4854 50  0000 R CNN
F 1 "2k2" H 1780 4945 50  0000 R CNN
F 2 "Resistor_SMD:R_0603_1608Metric_Pad0.84x1.00mm_HandSolder" V 1780 4900 50  0001 C CNN
F 3 "https://www.mouser.com/datasheet/2/447/PYu-RC_Group_51_RoHS_L_9-1314892.pdf" H 1850 4900 50  0001 C CNN
F 4 "603-RC0603FR-072K2L" H 1850 4900 50  0001 C CNN "Mouser_PN"
	1    1850 4900
	-1   0    0    1   
$EndComp
$EndSCHEMATC
