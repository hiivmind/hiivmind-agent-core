---
name: steady
description: Look up three names, one call at a time, with long reference notes.
inputs:
  stamp: a text unlike any other run's, so nothing of this node is in a cache before it runs
outputs: {}
exits: [done, failed]
allowed-tools: [lookup_revision]
---
# Steady

Run stamp: {{input.stamp}}.

## Steps

1. CALL `lookup_revision` with the name `alpha`, alone in its response. Wait for its result.
2. Do the same for `beta`, then `gamma`: one call in each response, each after the result of the one before.
3. When the third result is in, EXIT `done`.

## Reference notes

- Note 1: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 2: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 3: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 4: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 5: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 6: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 7: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 8: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 9: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 10: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 11: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 12: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 13: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 14: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 15: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 16: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 17: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 18: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 19: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 20: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 21: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 22: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 23: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 24: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 25: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 26: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 27: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 28: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 29: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 30: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 31: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 32: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 33: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 34: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 35: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 36: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 37: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 38: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 39: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 40: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 41: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 42: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 43: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 44: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 45: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 46: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 47: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 48: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 49: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 50: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 51: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 52: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 53: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 54: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 55: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 56: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 57: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 58: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 59: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 60: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 61: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 62: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 63: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 64: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 65: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 66: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 67: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 68: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 69: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 70: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 71: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 72: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 73: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 74: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 75: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 76: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 77: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 78: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 79: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 80: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 81: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 82: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 83: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 84: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 85: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 86: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 87: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 88: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 89: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 90: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 91: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 92: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 93: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 94: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 95: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 96: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 97: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 98: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 99: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 100: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 101: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 102: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 103: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 104: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 105: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 106: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 107: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 108: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 109: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 110: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 111: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 112: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 113: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 114: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 115: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 116: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 117: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 118: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 119: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 120: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 121: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 122: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 123: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 124: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 125: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 126: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 127: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 128: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 129: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 130: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 131: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 132: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 133: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 134: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 135: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 136: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 137: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 138: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 139: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 140: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 141: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 142: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 143: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 144: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 145: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 146: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 147: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 148: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 149: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 150: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 151: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 152: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 153: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 154: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 155: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 156: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 157: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 158: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 159: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
- Note 160: a source is named by a short word, its revision is a whole number, revisions are never negative, and a source that cannot be found is reported by the tool and is not an error of the one calling it.
