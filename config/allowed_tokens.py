"""
Official eligible BEP-20 token list for BNB Hack competition.
149 tokens from the competition contract.
Trades outside this list do NOT count toward PnL scoring.
"""

# Symbols -> known BSC contract addresses (mainnet)
# Addresses from BSCScan / CMC — verify before trading
ALLOWED_SYMBOLS = {
    "ETH", "USDT", "USDC", "XRP", "TRX", "DOGE", "ZEC", "ADA", "LINK", "BCH",
    "DAI", "TON", "USD1", "USDe", "M", "LTC", "AVAX", "SHIB", "XAUt", "WLFI",
    "H", "DOT", "UNI", "ASTER", "DEXE", "USDD", "ETC", "AAVE", "ATOM", "U",
    "STABLE", "FIL", "INJ", "NIGHT", "FET", "TUSD", "BONK", "PENGU", "CAKE",
    "SIREN", "LUNC", "ZRO", "KITE", "FDUSD", "BEAT", "PIEVERSE", "BTT", "NFT",
    "EDGE", "FLOKI", "LDO", "B", "FF", "PENDLE", "NEX", "STG", "AXS", "TWT",
    "HOME", "RAY", "COMP", "GWEI", "XCN", "GENIUS", "XPL", "BAT", "SKYAI",
    "APE", "IP", "SFP", "TAG", "NXPC", "AB", "SAHARA", "1INCH", "CHEEMS",
    "BANANAS31", "RIVER", "MYX", "RAVE", "SNX", "FORM", "LAB", "HTX", "USDf",
    "CTM", "BDX", "SLX", "UB", "DUCKY", "FRAX", "BILL", "WFI", "KOGE", "ALE",
    "FRXUSD", "USDF", "GOMINING", "VCNT", "GUA", "DUSD", "SMILEK", "0G",
    "BEAM", "MY", "SOON", "REAL", "Q", "AIOZ", "ZIG", "YFI", "TAC", "lisUSD",
    "CYS", "ZAMA", "TRIA", "HUMA", "PLUME", "ZIL", "XPR", "ZETA", "BabyDoge",
    "NILA", "ROSE", "VELO", "UAI", "BRETT", "OPEN", "BSB", "TOSHI", "BAS",
    "ACH", "AXL", "LUR", "ELF", "KAVA", "APR", "IRYS", "EURI", "XUSD", "BARD",
    "DUSK", "SUSHI", "PEAQ", "COAI", "BDCA", "XAUM",
}

# Known BSC contract addresses for top-volume tokens (for direct scan)
KNOWN_ADDRESSES = {
    "USDT":  "0x55d398326f99059fF775485246999027B3197955",
    "USDC":  "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "ETH":   "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "BUSD":  "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    "DAI":   "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3",
    "CAKE":  "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "XRP":   "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
    "ADA":   "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "DOGE":  "0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
    "LINK":  "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
    "DOT":   "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "LTC":   "0x4338665CBB7B2485A8855A139b75D5e34AB0DB94",
    "BCH":   "0x8fF795a6F4D97E7887C79beA79aba5cc76444aDf",
    "UNI":   "0xBf5140A22578168FD562DCcF235E5D43A02ce9B1",
    "AAVE":  "0xfb6115445Bff7b52FeB98650C87f44907E58f802",
    "ATOM":  "0x0Eb3a705fc54725037CC9e008bDede697f62F335",
    "AVAX":  "0x1CE0c2827e2eF14D5C4f29a091d735A204794041",
    "SHIB":  "0x2859e4544C4bB03966803b044A93563Bd2D0DD4D",
    "FIL":   "0x0D8Ce2A99Bb6e3B7Db580eD848240e4a0F9aE153",
    "FLOKI": "0xfb5B838b6cfEEdC2873aB27866079AC55363D37",
    "TWT":   "0x4B0F1812e5Df2A09796481Ff14017e6005508003",
    "PENDLE":"0xb3Ed0A426155B79B898849803E3B36552f7ED507",
    "DEXE":  "0x74B988156925937bD4E082f0eD7429Da8eAea8Db",
    "INJ":   "0xa2B726B1145A4773F68593CF171187d8EBe4d495",
    "FET":   "0x031b41e504677879370e9DBcF937283A8691Fa7f",
}

STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "FDUSD", "TUSD", "FRAX", "USDD", "USDe", "USD1", "FRXUSD", "USDF", "USDf", "XUSD", "DUSD", "lisUSD"}

BNB_NATIVE = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"  # WBNB

def is_allowed(symbol: str) -> bool:
    return symbol.upper() in ALLOWED_SYMBOLS

def is_stablecoin(symbol: str) -> bool:
    return symbol.upper() in STABLECOINS

def get_address(symbol: str) -> str | None:
    return KNOWN_ADDRESSES.get(symbol.upper())
