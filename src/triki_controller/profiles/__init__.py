"""Profile mapping."""

from triki_controller.profiles.builtin import Profile, profile_by_name
from triki_controller.profiles.devices import DeviceProfileMapper
from triki_controller.profiles.mapper import ProfileMapper, UnavailableProfileMapper

__all__ = [
    "DeviceProfileMapper",
    "Profile",
    "ProfileMapper",
    "UnavailableProfileMapper",
    "profile_by_name",
]
