from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pos_inventory_system.database.connection import get_connection


@dataclass(frozen=True)
class CommissionAgentFormData:
    name: str
    agent_code: str
    phone: str
    email: str
    commission_rate: float
    sales_target: float
    territory: str
    payout_frequency: str
    payable_account: str
    address: str
    notes: str
    is_active: int


class CommissionAgentRepository:
    def list_agents(self) -> list[sqlite3.Row]:
        with get_connection() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        id,
                        name,
                        agent_code,
                        phone,
                        email,
                        commission_rate,
                        sales_target,
                        territory,
                        payout_frequency,
                        payable_account,
                        address,
                        notes,
                        is_active,
                        created_at,
                        updated_at
                    FROM sales_commission_agents
                    ORDER BY created_at DESC, id DESC
                    """
                )
            )

    def create_agent(self, agent: CommissionAgentFormData) -> int:
        self._validate_agent(agent)

        with get_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sales_commission_agents (
                    name,
                    agent_code,
                    phone,
                    email,
                    commission_rate,
                    sales_target,
                    territory,
                    payout_frequency,
                    payable_account,
                    address,
                    notes,
                    is_active,
                    updated_at
                )
                VALUES (?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, ?, NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), NULLIF(?, ''), ?, CURRENT_TIMESTAMP)
                """,
                (
                    agent.name.strip(),
                    agent.agent_code.strip(),
                    agent.phone.strip(),
                    agent.email.strip(),
                    agent.commission_rate,
                    agent.sales_target,
                    agent.territory.strip(),
                    agent.payout_frequency.strip(),
                    agent.payable_account.strip(),
                    agent.address.strip(),
                    agent.notes.strip(),
                    agent.is_active,
                ),
            )
            return int(cursor.lastrowid)

    def update_agent(self, agent_id: int, agent: CommissionAgentFormData) -> None:
        if agent_id <= 0:
            raise ValueError("Agent is required.")
        self._validate_agent(agent)

        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE sales_commission_agents
                SET
                    name = ?,
                    agent_code = NULLIF(?, ''),
                    phone = NULLIF(?, ''),
                    email = NULLIF(?, ''),
                    commission_rate = ?,
                    sales_target = ?,
                    territory = NULLIF(?, ''),
                    payout_frequency = NULLIF(?, ''),
                    payable_account = NULLIF(?, ''),
                    address = NULLIF(?, ''),
                    notes = NULLIF(?, ''),
                    is_active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    agent.name.strip(),
                    agent.agent_code.strip(),
                    agent.phone.strip(),
                    agent.email.strip(),
                    agent.commission_rate,
                    agent.sales_target,
                    agent.territory.strip(),
                    agent.payout_frequency.strip(),
                    agent.payable_account.strip(),
                    agent.address.strip(),
                    agent.notes.strip(),
                    agent.is_active,
                    agent_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("Commission agent was not found.")

    def _validate_agent(self, agent: CommissionAgentFormData) -> None:
        if not agent.name.strip():
            raise ValueError("Agent name is required.")
        if agent.commission_rate < 0:
            raise ValueError("Commission rate cannot be negative.")
        if agent.commission_rate > 100:
            raise ValueError("Commission rate cannot be more than 100.")
        if agent.sales_target < 0:
            raise ValueError("Sales target cannot be negative.")
