#include "pch.hpp"

void f::grenades::get_data(c_base_entity* entity, const std::string& class_name)
{
	const auto scene_origin = entity->get_scene_origin();
	if (scene_origin.is_zero())
		return;

	nlohmann::json grenade_data = {};
	grenade_data["x"] = scene_origin.m_x;
	grenade_data["y"] = scene_origin.m_y;
	grenade_data["z"] = scene_origin.m_z;

	const auto hashed = fnv1a::hash(class_name);

	if (hashed == fnv1a::hash("C_SmokeGrenadeProjectile"))
	{
		// m_bDidSmokeEffect — hardcoded offset (not in schema system)
		const auto did_smoke = m_memory->read_t<bool>(reinterpret_cast<uintptr_t>(entity) + 0x11B8);
		if (!did_smoke)
			return;

		grenade_data["type"] = "smoke";
	}
	else if (hashed == fnv1a::hash("C_MolotovProjectile") ||
	         hashed == fnv1a::hash("C_Inferno"))
	{
		grenade_data["type"] = "molly";
	}
	else if (hashed == fnv1a::hash("C_HEGrenadeProjectile"))
	{
		grenade_data["type"] = "he";
	}
	else if (hashed == fnv1a::hash("C_Flashbang"))
	{
		grenade_data["type"] = "flash";
	}
	else
	{
		return;
	}

	m_data["m_grenades"].push_back(grenade_data);
}
