"""
Per-device identification profiles, recovered from Datalyse.exe.

All identification commands and their expected answers below come from the
string tables referenced by the single giant dispatcher function at
``0x0047FB84`` (see ``decompiled/ghidra/decomp/0047FB84_FUN_0047fb84.c``, the
"referenced strings" block starting around VA 0x00485458).  Every literal in
that block sits in the driver dispatch, so a pair like ``*IDN?`` next to
``FLUKE, 45`` is the actual probe/answer sequence for the Fluke 8845A.

Serial settings (baud/parity/stop/data) are not in the string table; each one
here is attributed to the vendor help page that documents it, noted in
``docs``.

Entry shape::

    number: DeviceProfile(
        name="...",              # as written in Datalyse.ini
        driver="...",            # key in drivers/catalog.py, or None
        id_command="...",        # None => the device has no version code
        id_expect=("...",),      # substring the answer must contain
        serial=(baud, bits, parity, stop),
        docs="...",              # help page the serial settings come from
    )

``id_command=None`` with ``note=`` reproducing the program's own message
("... has no version code") means the original cannot identify the device
either and simply starts measuring -- Datalyse shows that text in a dialog.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .base import SerialParams


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    driver: str | None = None
    id_command: str | None = None
    id_expect: tuple[str, ...] = ()
    serial: SerialParams | None = None
    measure_command: str | None = None
    channels: tuple[str, ...] = ("value",)
    units: tuple[str, ...] = ("",)
    docs: str = ""
    note: str = ""


def S(baud=9600, bits=8, parity="N", stop=1):
    return SerialParams(baudrate=baud, bytesize=bits, parity=parity, stopbits=stop)


# Devices that share the standard "IMPO handheld" behaviour: 9600/N/1/8 with
# command 'V' for version.  Documented on handimpo.htm for every meter in the
# family (conductivity, lux, manometer, O2, pH, radioactivity, temperature).
_IMPO = dict(serial=S(9600, 8, "N", 1), id_command="V", id_expect=("V",),
             driver="impo_handheld", docs="handimpo.htm")

DEVICE_PROFILES: dict[int, DeviceProfile] = {
    1: DeviceProfile("pt200 thermometer", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                     docs="handimpo.htm", note="PT200 temperature meter, IMPO"),
    2: DeviceProfile("dmi24 multimeter", "dmi24", "v", ("dmi24", "t1"), S(9600, 8, "N", 1),
                     measure_command="t1", docs="Frederiksen.htm"),
    3: DeviceProfile("Fluke 8845A", "fluke8845a", "*IDN?", ("FLUKE", "45"), S(9600, 8, "N", 2),
                     measure_command="VAL1?", docs="fluke.htm"),
    4: DeviceProfile("EM1 energymeter", "generic", "V", ("EM1",), S(9600, 8, "N", 1),
                     channels=("E", "U", "I", "P"), docs="elcanic.htm"),
    5: DeviceProfile("MI multiinterface", "generic", "V", ("MI",), S(9600, 8, "N", 1),
                     channels=("t", "U"), docs="elcanic.htm"),
    6: DeviceProfile("FD4E function generator", "generic", "V", ("FD4E",), S(9600, 8, "N", 1),
                     docs="elcanic.htm"),
    7: DeviceProfile("pH1000 pH meter", "generic", "V", ("PH1000",), S(9600, 8, "N", 1),
                     channels=("pH",), docs="handimpo.htm"),
    8: DeviceProfile("MC-24E 4.x Counter", "generic", "V", ("MC24E",), S(9600, 8, "N", 1),
                     channels=("counts",), docs="elcanic.htm"),
    9: DeviceProfile("Bosch BS, EP, DMS", "bosch", "w", (), S(1200, 8, "N", 1),
                     measure_command="w", channels=("mass",), units=("g",), docs="boschvgt.htm",
                     note="BS series 8 data bits; EP/DMS 7 data bits; original retries at 7/2"),
    10: DeviceProfile("Mettler college balance", None, None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—", note="protocol not documented"),
    11: DeviceProfile("pHM 92 phmeter", "phm", "?TY", ("pHM", "Radiometer"),
                      S(2400, 7, "E", 1), channels=("pH",), docs="—",
                      note="Radiometer pHM family, '?TY' query from the dispatch table"),
    12: DeviceProfile("Metex multimeter", "generic", "D", (), S(1200, 8, "N", 1),
                      measure_command="D", docs="—",
                      note="'Metex has no version code, a measurement will be made:' "
                           "'Do not use the COMM-button on Metex!' ('{O'/'}O' framing)"),
    13: DeviceProfile("Sartorius Basic balance", None, None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—",
                      note="'Sartorius has no version code, a measurement will be made:'"),
    14: DeviceProfile("GM-counter", "generic", "V", ("GM-counter",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="Frederiksen.htm"),
    15: DeviceProfile("Function Generator", "generic", "V", ("Function Generator",),
                      S(1200, 8, "N", 1), units=("Hz",), docs="Frederiksen.htm"),
    16: DeviceProfile("Watt- and energymeter", "generic", "V", ("Watt- & Energymeter",),
                      S(1200, 8, "N", 1), channels=("P", "E"), docs="Frederiksen.htm"),
    17: DeviceProfile("Digital multimeter", "generic", "V", (), S(1200, 8, "N", 1),
                      docs="Frederiksen.htm", note="'B0'/'B2' select 1200/9600 baud"),
    18: DeviceProfile("RM3 ratemeter", "generic", "V", ("RM3",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="—"),
    19: DeviceProfile("RM2 ratemeter", "generic", "V", ("RM2",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="—"),
    20: DeviceProfile("Consort P601", "consort", "8", (), S(2400, 8, "N", 1),
                      measure_command="8", channels=("value", "temperature"),
                      units=("", "°C"), docs="consort.htm"),
    21: DeviceProfile("Kern EW balance", "generic", "O8", ("Kern EW",), S(1200, 7, "E", 1),
                      units=("g",), docs="—", note="'Kern EW: O8'"),
    22: DeviceProfile("elma/BEHA 2730 multimeter", "elma2730", None, (), S(9600, 8, "N", 1),
                      docs="elmabeha.htm",
                      note="send a space with no CR/LF, 5-byte answer"),
    23: DeviceProfile("MC24 counter 2.3", "generic", None, (), S(9600, 8, "N", 1),
                      channels=("counts",), docs="elcanic.htm",
                      note="'MC24 2.3 has no version code!'"),
    24: DeviceProfile("FD4 funktion generator", "generic", None, (), S(9600, 8, "N", 1),
                      units=("Hz",), docs="—", note="'fd4' identifier"),
    25: DeviceProfile("elma 2732 multimeter with datalog", "elma2730", None, (),
                      S(9600, 8, "N", 1), docs="elmabeha.htm",
                      note="2730 protocol plus a 4048-byte datalog"),
    26: DeviceProfile("TES 2732 multimeter with datalog", "elma2730", None, (),
                      S(9600, 8, "N", 1), docs="elmabeha.htm",
                      note="identical to the elma 2732, different branding"),
    27: DeviceProfile("A&D:E K,EW balances", "generic", None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—",
                      note="'A&D balances have no version code,'"),
    28: DeviceProfile("Lambda 2", "generic", "$ST", ("Lambda2",), S(9600, 8, "N", 1),
                      docs="—"),
    29: DeviceProfile("BioOrbit 1253 luminometer", "generic", "I4", (), S(9600, 8, "N", 1),
                      docs="bioorbit.htm", note="'BioOrbit luminometer'"),
    30: DeviceProfile("Mettler Delta Range balance", None, None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—"),
    31: DeviceProfile("Oxygen Meter DO-5510", "generic", "ES", (), S(9600, 8, "N", 1),
                      channels=("O2",), docs="—",
                      note="'STANDARD  V1.7' / 'Oxygen Meter has no version code.'"),
    32: DeviceProfile("mVolt METER", "generic", "id", (), S(9600, 8, "N", 1), docs="—"),
    33: DeviceProfile("Keithley 2000 multimeter", "generic", ":SYSTem:VERSion?",
                      ("Keithley", "1991.0"), S(9600, 8, "N", 1), measure_command="INIT:CONT OFF;:ABORT",
                      docs="—", note="SCPI; switched OFF in the shipped Datalyse.ini"),
    34: DeviceProfile("Shimadzu spectrophotometer", "generic", None, (), S(9600, 8, "N", 1),
                      docs="—", note="'Shimadzu has no version code.'"),
    35: DeviceProfile("DT4 Temperature Meter", "generic", "DT4", ("DT4",), S(9600, 8, "N", 1),
                      channels=("t",), units=("°C",), docs="—"),
    36: DeviceProfile("BOSCH SAE balance", "bosch", None, (), S(9600, 7, "O", 1),
                      units=("g",), docs="boschvgt.htm",
                      note="'Bosch SAE has no version code, a measurement will be made:'"),
    37: DeviceProfile("2001 Scaler-Timer", "sf", "V", ("SF 2001", "2001"), S(9600, 8, "N", 1),
                      docs="Frederiksen.htm"),
    38: DeviceProfile("Shinko Vibra balance", "shinko", "O8", ("Shinko",), S(1200, 7, "E", 1),
                      units=("g",), docs="—", note="'Shinko: O8'"),
    39: DeviceProfile("AC7E Counter", "generic", "AC7E", ("AC7E",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="—"),
    40: DeviceProfile("Sound card", "generic", None, (), None, docs="lydkort.htm",
                      note="driven through WinMM waveIn, not a serial port"),
    41: DeviceProfile("pHM 93 pH meter", "phm", "?TY", ("pHM 93",), S(2400, 7, "E", 1),
                      channels=("pH",), docs="—"),
    42: DeviceProfile("pHM 240 pH/ion meter", "phm", "BD", ("pHM240",), S(2400, 7, "E", 1),
                      channels=("pH",), docs="—"),
    43: DeviceProfile("Mettler BD202 balance", None, None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—"),
    44: DeviceProfile("Hitachi spectrophotometer", "generic", None, (), S(4800, 8, "N", 1),
                      docs="hitachi.htm", note="'Hitachi has no version code.'"),
    45: DeviceProfile("pHM 220 Lab pH meter", "phm", "?TY", ("pHM220",), S(2400, 7, "E", 1),
                      channels=("pH",), docs="—"),
    46: DeviceProfile("pHM250 ION analyzer", "phm", "?TY", ("pHM250",), S(2400, 7, "E", 1),
                      channels=("pH",), docs="—"),
    47: DeviceProfile("CDM 210 conductivity meter", "phm", "=TY CDM210", ("CDM210",),
                      S(2400, 7, "E", 1), channels=("S/cm",), docs="—"),
    48: DeviceProfile("PHM 210 standard pH meter", "phm", "=TY PHM210", ("PHM210",),
                      S(2400, 7, "E", 1), channels=("pH",), docs="—"),
    49: DeviceProfile("PTM100 pressure and temperature", "generic", "PTM100", ("PTM100",),
                      S(9600, 8, "N", 1), channels=("P", "t"), docs="elcanic.htm"),
    51: DeviceProfile("RM400 counter", "generic", "%RM400", ("RM400",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="elcanic.htm"),
    52: DeviceProfile("Ultraspec II spectrophotometer", "generic", None, (), S(9600, 8, "N", 1),
                      docs="—"),
    53: DeviceProfile("Spectronic 301", "genesys", "REV", ("SPEC",), S(9600, 8, "N", 1),
                      channels=("A",), docs="genesys.htm"),
    54: DeviceProfile("Spectronic 20 Genesys", "genesys", "REV", ("SPEC 20 GENESYS",),
                      S(9600, 8, "N", 1), channels=("A",), docs="genesys.htm",
                      note="'Changing baudrate to 9600' via 'BAUD 9600'"),
    55: DeviceProfile("pHTM105 pH/Temperature-Meter", "generic", "(PHTM105",
                      ("PHTM105",), S(9600, 8, "N", 1), channels=("pH", "t"),
                      docs="elcanic.htm"),
    56: DeviceProfile("elma 1353 Sound Level Meter", "generic", None, (), S(9600, 8, "N", 1),
                      units=("dB",), docs="—"),
    57: DeviceProfile("Ultrospec 3000 spectrophotometer", "generic", None, (),
                      S(9600, 8, "N", 1), docs="—",
                      note="'! Ultraspec 3000 warming, wait' / 'E93 Busy'"),
    58: DeviceProfile("Light Meter RS 180-7133", "generic", None, (), S(9600, 8, "N", 1),
                      units=("lux",), docs="—", note="'Light Meter has no version code.'"),
    59: DeviceProfile("Jenway 6405 (6400)", "generic", None, (), S(9600, 8, "N", 1),
                      docs="—", note="'Jenway should display start menu'"),
    60: DeviceProfile("phywe spectrophotometer", "generic", "?****",
                      ("Phywe spectrophotometer",), S(9600, 8, "N", 1), channels=("A",),
                      docs="—"),
    61: DeviceProfile("Datalogger 755", "generic", None, (), S(9600, 8, "N", 1),
                      channels=("a1", "a2", "a3", "a4", "a5", "t1", "t2"), docs="elcanic.htm",
                      note="'Skolelog 755': 5 analogue 0-10 V, 2 temperature, 2 frequency, "
                           "1 counter input, 3 analogue outputs, 3 relays, 1948-byte log"),
    62: DeviceProfile("Temperature-meter IMPO", **_IMPO),
    63: DeviceProfile("Function Generator HM8130", "hameg", None, (), S(9600, 8, "N", 1),
                      units=("Hz",), docs="hameg81.htm"),
    64: DeviceProfile("Fluke 867B multimeter", "fluke867b", "ID", (), S(19200, 8, "N", 1),
                      docs="fluke.htm", note="answers two spaces; ~900 bytes per scope image"),
    65: DeviceProfile("Anemometer AM 4204", "generic", None, (), S(9600, 8, "N", 1),
                      units=("m/s",), docs="anemo.htm", note="'AM-4204 has no version code'"),
    66: DeviceProfile("Hameg HM 407 oscilloscope", "hameg", "ID:HM407", ("HM407",),
                      S(38400, 8, "N", 2), docs="hamg407.htm",
                      note="automatic baud rate detection; 25 bits per sample"),
    67: DeviceProfile("Conductivity-Meter IMPO", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                      channels=("S/cm", "t"), docs="handimpo.htm"),
    68: DeviceProfile("pH/mV-Meter IMPO", "impo_handheld", "SI", (), S(9600, 8, "N", 1),
                      channels=("pH",), docs="handimpo.htm",
                      note="'The pH Meter has no version code.'"),
    69: DeviceProfile("A&D balances", "generic", None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—", note="'Kern balances'"),
    70: DeviceProfile("Jenway pH Meter 3310,3320", "generic", None, (), S(9600, 8, "N", 1),
                      channels=("pH",), docs="—", note="'Jenway pH Meter '"),
    71: DeviceProfile("WPA lightwave spectrophotometer", "generic", None, (),
                      S(9600, 8, "N", 1), docs="—", note="'WPA Lightwave has no codes!'"),
    72: DeviceProfile("Energymeter ENG110", "generic", "(ENG110", ("ENG110",),
                      S(9600, 8, "N", 1), channels=("E", "P"), docs="elcanic.htm"),
    73: DeviceProfile("DMG multimeter", "generic", None, (), S(9600, 8, "N", 1),
                      docs="dmg.htm", note="'DMG meter has no version code.'"),
    74: DeviceProfile("Prema multimeter 5017", "generic", "PREMA GmbH,5017",
                      ("PREMA", "5017"), S(9600, 8, "N", 1), docs="—"),
    75: DeviceProfile("TES 2730 Multimeter",
                     **_IMPO | {"driver": "elma2730", "id_command": None, "id_expect": (),
                                "docs": "elmabeha.htm"}),
    76: DeviceProfile("TES 1352 Sound Level Meter", "generic", None, (), S(9600, 8, "N", 1),
                      units=("dB",), docs="—"),
    77: DeviceProfile("Bell 5080 Teslameter", "generic", "*idn?", ("F.W.BELL", "5080"),
                      S(9600, 8, "N", 1), units=("T",), docs="bell5080.htm"),
    78: DeviceProfile("Jenway DO2 Meter 9200", "generic", None, (), S(9600, 8, "N", 1),
                      channels=("O2",), docs="—",
                      note="'Jenway DO2 Meter can only read log!'"),
    79: DeviceProfile("Jenway 6300 spectrophotometer", "generic", None, (),
                      S(9600, 8, "N", 1), channels=("A",), docs="—"),
    80: DeviceProfile("Cecil 1011 spectrophotometer", "generic", "CECIL  CE 1011",
                      ("CECIL", "1011"), S(9600, 7, "E", 2), channels=("A",), docs="cecil.htm"),
    81: DeviceProfile("FNG120 function generator", "generic", "FNG120", ("FNG120",),
                      S(9600, 8, "N", 1), units=("Hz",), docs="elcanic.htm"),
    82: DeviceProfile("Hameg HM1507-2 oscilloscope", "hameg", "ID:HM1507-2",
                      ("HM1507",), S(19200, 8, "N", 1), docs="hameg81.htm"),
    83: DeviceProfile("Cecil 2041 UV/VIS spectrophotometer", "generic", "CECIL  CE 2041",
                      ("CECIL", "2041"), S(9600, 7, "E", 2), channels=("A",), docs="cecil.htm"),
    84: DeviceProfile("Multilog DB-526", "generic", "Multilog DB-526, vers:",
                      ("Multilog DB-526",), S(9600, 8, "N", 1),
                      channels=tuple(f"in{i}" for i in range(1, 9)), docs="—"),
    85: DeviceProfile("ABU93 triburette", "generic", "ABU 93", ("ABU 93",), S(9600, 7, "E", 1),
                      channels=("ml",), docs="abu93.htm"),
    86: DeviceProfile("Ecolog", "generic", "Ecolog ECL-", ("Ecolog ECL-",),
                      S(9600, 8, "N", 1), docs="ecolog.htm"),
    87: DeviceProfile("CNT150 counter", "generic", "CNT150", ("CNT150",), S(9600, 8, "N", 1),
                      channels=("counts",), docs="elcanic.htm",
                      note="'#GM#' marks a Geiger tube reading"),
    88: DeviceProfile("EXTECH thermometer", "extech", None, (), S(9600, 8, "N", 1),
                      channels=("t1", "t2"), units=("°C", "°C"), docs="extech.htm",
                      note="send a space with no CR/LF, 7-byte answer, RTS low"),
    89: DeviceProfile("Voltcraft VC 820, VC 840", "generic", "VC506", (), S(2400, 8, "N", 1),
                      docs="—", note="shares device 89 with Brymen 202 in the shipped ini"),
    90: DeviceProfile("Spectronic Genesys 8", "genesys", "GENESYS8", ("GENESYS8",),
                      S(9600, 8, "N", 1), channels=("A",), docs="genesys.htm"),
    91: DeviceProfile("Shimadzu UVmini 1240", "generic", None, (), S(9600, 8, "N", 1),
                      channels=("A",), docs="—", note="'Shimadzu has no version code.'"),
    92: DeviceProfile("Kern EW balance", "generic", "Kern EW", ("Kern EW",),
                      S(1200, 7, "E", 1), units=("g",), docs="—"),
    93: DeviceProfile("CBL", "generic", "CBL", ("CBL",), S(9600, 8, "N", 1), docs="cbl.htm"),
    94: DeviceProfile("CBR", "generic", "CBR", ("CBR",), S(9600, 8, "N", 1),
                      channels=("x",), units=("m",), docs="cbl.htm",
                      note="'CBR, device code: '"),
    95: DeviceProfile("DM450 multimeter", "generic", "DM 450", ("DM 450", "DM_450"),
                      S(9600, 8, "N", 1), docs="elcanic.htm"),
    96: DeviceProfile("Manometer", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                      channels=("P",), docs="handimpo.htm", note="'Mano/Baro-Meter'"),
    97: DeviceProfile("ME-31(roline)", "generic", None, (), S(9600, 8, "N", 1),
                      docs="—", note="'ME 31 has no version code.'"),
    98: DeviceProfile("2002 Scaler-Timer", "sf", "V", ("2002",), S(9600, 8, "N", 1),
                      docs="Frederiksen.htm", note="'2002.50', 'E1'"),
    99: DeviceProfile("Kern 440 balance", "generic", None, (), S(1200, 7, "E", 1),
                      units=("g",), docs="—"),
    100: DeviceProfile("Geiger-Müller Counter", "generic", "513600 GM Counter",
                       ("513600", "GM Counter"), S(9600, 8, "N", 1), channels=("counts",),
                       docs="Frederiksen.htm"),
    101: DeviceProfile("MetraHIT multimeter", "generic", None, (), S(9600, 8, "N", 1),
                       docs="—"),
    102: DeviceProfile("LabPro", "generic", "LabPro", ("LabPro",), S(9600, 8, "N", 1),
                       docs="—", note="'888' / 'LabPro '"),
    103: DeviceProfile("CBL2", "generic", "CBL 2", ("CBL 2",), S(9600, 8, "N", 1),
                       docs="cbl2.htm", note="'CBL 2, vers. '"),
    104: DeviceProfile("Unicam Helios e", "generic", "UNICAM Helios e",
                       ("UNICAM Helios e",), S(9600, 8, "N", 1), channels=("A",),
                       docs="genesys.htm"),
    105: DeviceProfile("Acculab LA-110 balance", "generic", None, (), S(1200, 7, "O", 1),
                       units=("g",), docs="acculab.htm",
                       note="'Acculab has no version code, a measurement will be made:'"),
    106: DeviceProfile("Mastech MAS-345 multimeter", "generic", None, (), S(9600, 8, "N", 1),
                       docs="—", note="'MAS-345 has no version code.'"),
    107: DeviceProfile("TES 1362 Humidity/Temperature Meter", "generic", None, (),
                       S(9600, 8, "N", 1), channels=("RH", "t"), docs="—"),
    108: DeviceProfile("TES 1336 Light Meter", "generic", None, (), S(9600, 8, "N", 1),
                       units=("lux",), docs="—"),
    109: DeviceProfile("TES 1353 Sound Level Meter", "generic", None, (), S(9600, 8, "N", 1),
                       units=("dB",), docs="—"),
    110: DeviceProfile("TES 1380 pH/ORP/temperature", "generic", None, (),
                       S(9600, 8, "N", 1), channels=("pH", "t"), docs="—"),
    111: DeviceProfile("DiVA Spectrometer", "generic", None, (), S(9600, 8, "N", 1),
                       docs="diva.htm", note="wavelength calibration from Diva.ini"),
    113: DeviceProfile("Jenway spectrophotometer", "generic", None, (), S(9600, 8, "N", 1),
                       channels=("A",), docs="—"),
    114: DeviceProfile("Hitachi U-1100 spectrofotometer", "generic", None, (),
                       S(4800, 8, "N", 1), channels=("A",), docs="hitachi.htm",
                       note="'Hitachi U-1000/U-1100'"),
    115: DeviceProfile("MP230 pH meter", "generic", None, (), S(9600, 8, "N", 1),
                       channels=("pH",), docs="—", note="Mettler Toledo"),
    116: DeviceProfile("MPC227 pH/conductivity Meter", "generic", None, (),
                       S(9600, 8, "N", 1), channels=("pH", "S/cm"), docs="—"),
    118: DeviceProfile("Voltcraft VC506", "generic", "VC506", ("VC506",), S(9600, 8, "N", 1),
                       docs="—", note="'RS232 constant on! (Menu, Enter)'"),
    119: DeviceProfile("ADP220 polarimeter", "generic", "ADP220", ("ADP220",),
                       S(9600, 8, "N", 1), channels=("angle",), docs="adp220.htm"),
    120: DeviceProfile("Protek 506 multimeter", "generic", "Protek 506", ("Protek 506",),
                       S(9600, 8, "N", 1), docs="—",
                       note="'RS232 constant on? (Menu, Enter)'"),
    121: DeviceProfile("Helios Gamma", "generic", "HELIOS G", ("HELIOS G",),
                       S(9600, 8, "N", 1), channels=("A",), docs="genesys.htm"),
    123: DeviceProfile("Consort C831 multi-parameter analyser", "consort",
                       "CONSORT C831", ("Consort C831",), S(2400, 8, "N", 1),
                       measure_command="8", channels=("value", "temperature"),
                       units=("", "°C"), docs="consort.htm",
                       note="'CONSORT C831 should display pH, mV or uS.'"),
    124: DeviceProfile("TitroLine 96", "generic", "Ident:TitroLine 96",
                       ("TitroLine 96",), S(9600, 8, "N", 1), channels=("ml", "pH"),
                       docs="—", note="'ERROR:Command' / 'EX' replies on error"),
    125: DeviceProfile("TECPEL 331 Sound Level Meter", "generic", None, (),
                       S(9600, 8, "N", 1), units=("dB",), docs="—"),
    126: DeviceProfile("Genesys 10 Uis and UV-Vis", "genesys", "MODEL",
                       ("MODELGENESYS 10",), S(19200, 8, "N", 1), channels=("A",),
                       docs="genesys.htm"),
    127: DeviceProfile("Genesys 6 UV/Vis", "genesys", "MODEL", ("MODELGENESYS 6",),
                       S(9600, 8, "N", 1), channels=("A",), docs="genesys.htm"),
    128: DeviceProfile("LUX-meter 1540-10", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                       units=("lux",), docs="handimpo.htm", note="'Lux-Meter'"),
    129: DeviceProfile("O2-meter 1560", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                       channels=("O2",), docs="handimpo.htm", note="'O2-Meter'"),
    131: DeviceProfile("UNICO UV-Spectrophotometer", "generic", None, (),
                       S(9600, 8, "N", 1), channels=("A",), docs="—",
                       note="'UNICO spectrophotometer'"),
    133: DeviceProfile("Turbidity kit", "generic", None, (), S(9600, 8, "N", 1),
                       units=("NTU",), docs="—", note="'Turbidity', 'error'"),
    134: DeviceProfile("Kern EG 420", "generic", None, (), S(1200, 7, "E", 1),
                       units=("g",), docs="—"),
    135: DeviceProfile("Tritronic Basic", "generic", None, (), S(9600, 8, "N", 1),
                       channels=("ml", "pH"), docs="—"),
    136: DeviceProfile("DMI4 Multemeter", "dmi4", "V", ("DMI4",), S(9600, 8, "N", 1),
                       channels=("t", "pH", "P", "value"), docs="Frederiksen.htm",
                       note="four galvanically separated sections"),
    137: DeviceProfile("Radioactivitymeter", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                       channels=("cps",), docs="handimpo.htm", note="'Radioactivity-Meter'"),
    138: DeviceProfile("Lux-meter 3876", "impo_handheld", "V", (), S(9600, 8, "N", 1),
                       units=("lux",), docs="handimpo.htm", note="'Lux-Meter 3876'"),
}


# ---------------------------------------------------------------------------
# Devices the dispatcher cannot identify.
#
# For these Datalyse has no version exchange -- it says so itself in a dialog
# ("... has no version code, a measurement will be made:") and goes straight to
# measuring.  The notes below record that, so a driver author can see exactly
# which devices still need a protocol capture.
# ---------------------------------------------------------------------------
_NO_VERSION_NOTE = {
    30: "no version exchange in the dispatcher; Mettler Delta Range protocol undocumented",
    43: "no version exchange; Mettler BD202 balances share the A&D/Sartorius line format",
    52: "'Ultraspec II' has no version code in the dispatcher",
    56: "elma 1353 sound level meter: no version code",
    63: "Hameg HM8130: no version exchange recovered (HM407/HM1507 use 'ID:HM...')",
    75: "TES 2730 is the same 5-byte protocol as the elma 2730, with no version code",
    76: "TES 1352 sound level meter: no version code",
    79: "Jenway 6300: no version code",
    99: "Kern 440 balance: no version code",
    101: "MetraHIT multimeter: no version code",
    107: "TES 1362 humidity/temperature meter: no version code",
    108: "TES 1336 light meter: no version code",
    109: "TES 1353 sound level meter: no version code",
    110: "TES 1380 pH/ORP/temperature meter: no version code",
    113: "Jenway spectrophotometer: no version code",
    116: "Mettler Toledo MPC227: no version code",
    125: "TECPEL 331 sound level meter: no version code",
    134: "Kern EG 420 balance: no version code",
    135: "Tritronic Basic burette: no version code",
    # taken from Datalyse.ini itself: these numbers are deliberately unused
    50: "marked 'not used' in Datalyse.ini",
    112: "marked 'not used' in Datalyse.ini",
    117: "marked 'not used (Hameg scope)' in Datalyse.ini",
    122: "marked 'not used (TI-83 Plus)' in Datalyse.ini",
    130: "marked 'not used' in Datalyse.ini",
    132: "marked 'not used' in Datalyse.ini",
}

#: placeholders for the numbers Datalyse.ini reserves but never implements
_PLACEHOLDERS = {
    50: "not used", 112: "not used", 117: "not used (Hameg scope)",
    122: "not used (TI-83 Plus)", 130: "not used", 132: "not used",
}

for _num, _name in _PLACEHOLDERS.items():
    DEVICE_PROFILES[_num] = DeviceProfile(_name, None, None, (), None,
                                          docs="Datalyse.ini")

for _num, _note in _NO_VERSION_NOTE.items():
    _p = DEVICE_PROFILES.get(_num)
    if _p is not None and not _p.note:
        DEVICE_PROFILES[_num] = replace(_p, note=_note)


def profile(number: int) -> DeviceProfile | None:
    return DEVICE_PROFILES.get(number)


def find_by_name(name: str) -> DeviceProfile | None:
    """Match a `DEVICE,...` description from Datalyse.ini to a profile."""
    low = (name or "").lower().strip()
    if not low:
        return None
    best = None
    for p in DEVICE_PROFILES.values():
        pn = p.name.lower()
        if pn == low:
            return p
        if pn and (pn in low or low in pn) and best is None:
            best = p
    return best
