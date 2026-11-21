"""Fail closed when map extent exceeds actual model/product coverage."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Extent:
    west: float
    south: float
    east: float
    north: float
    def valid(self):
        return (-180 <= self.west < self.east <= 180 and
                -90 <= self.south < self.north <= 90)

def available_extent(requested, published):
    """Only permit bounds fully covered by a real published product tile."""
    if not requested.valid():
        return None
    for tile in published:
        if (tile.valid() and tile.west <= requested.west and
            tile.east >= requested.east and tile.south <= requested.south and
            tile.north >= requested.north):
            return requested
    return None
