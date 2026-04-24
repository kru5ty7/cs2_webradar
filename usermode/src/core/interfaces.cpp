#include "pch.hpp"

bool i::setup()
{
	bool success = true;

	const auto [client_base, client_size] = m_memory->get_module_info(CLIENT_DLL);
	if (!client_base.has_value() || !client_size.has_value())
		return {};

	const auto schema_system_pat = m_memory->find_pattern(SCHEMASYSTEM_DLL, GET_SCHEMA_SYSTEM);
	if (!schema_system_pat) { LOG_ERROR("GET_SCHEMA_SYSTEM pattern not found"); return {}; }
	m_schema_system = schema_system_pat->rip().as<c_schema_system*>();
	success &= (m_schema_system != nullptr);

	const auto global_vars_pat = m_memory->find_pattern(CLIENT_DLL, GET_GLOBAL_VARS);
	if (!global_vars_pat) { LOG_ERROR("GET_GLOBAL_VARS pattern not found"); return {}; }
	m_global_vars = m_memory->read_t<c_global_vars*>(global_vars_pat->rip().as<c_global_vars*>());
	success &= (m_global_vars != nullptr);

	const auto entity_list_pat = m_memory->find_pattern(CLIENT_DLL, GET_ENTITY_LIST);
	if (!entity_list_pat) { LOG_ERROR("GET_ENTITY_LIST pattern not found"); return {}; }
	m_game_entity_system = m_memory->read_t<c_game_entity_system*>(entity_list_pat->rip().as<c_game_entity_system*>());
	success &= (m_game_entity_system != nullptr);

	return success;
}