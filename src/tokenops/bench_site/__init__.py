"""Custom demo website for the governed browser-agent scenario.

Deterministic trap pages, each mapped to one control-plane capability:
  /loop  recursive navigation      -> progress_guard / loop guard
  /easy  trivial extract           -> model routing (cheap model)
  /hard  dense reasoning           -> model routing (strong model)
  /huge  ~5k-row DOM               -> context compaction
  /      stable header/nav/sidebar -> prompt caching (cacheable prefix)
"""
