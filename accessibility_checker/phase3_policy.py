"""Section 5 whitespace policy for 1.1.1 Non-text Content and 2.4.2 Page Titled."""

# Exact Unicode White_Space list in the guide; deliberately excludes U+200B
# and U+001C..U+001F (which Python's no-argument strip also considers whitespace).
UNICODE_WHITE_SPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)
