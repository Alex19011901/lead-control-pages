from __future__ import annotations


# Historical Telegram lead messages sent by the account whose stable
# Telegram user id is 1366518980. Older imported lead events did not preserve
# the sender id, so these message ids are used only to apply the same standing
# Cebikova/Tatiana exclusion retroactively to those already-imported leads.
LEGACY_TATIANA_TELEGRAM_MESSAGE_IDS = frozenset({
    5355, 5357, 5369, 5371, 5373, 5375, 5377, 5394, 5396, 5398, 5400, 5402, 5404, 5406, 5408, 5410, 5413, 5415, 5417, 5419,
    5421, 5423, 5425, 5428, 5440, 5446, 5449, 5466, 5468, 5470, 5472, 5474, 5476, 5478, 5480, 5483, 5488, 5489, 5491, 5495,
    5502, 5504, 5506, 5508, 5514, 5521, 5525, 5528, 5530, 5538, 5539, 5544, 5549, 5551, 5553, 5555, 5557, 5562, 5575, 5577,
    5579, 5581, 5583, 5593, 5595, 5603, 5605, 5607, 5609, 5614, 5617, 5623, 5625, 5627, 5631, 5635, 5642, 5653, 5655, 5657,
    5661, 5663, 5668,
})
