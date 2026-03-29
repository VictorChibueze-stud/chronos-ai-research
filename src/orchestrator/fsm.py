from transitions import Machine


class SetupFSM:
    """Finite state machine for monitored setup lifecycle."""

    states = ["SCANNING", "MONITORING", "IN_TRADE", "INVALID", "EXPIRED"]

    def __init__(self, initial_state: str = "SCANNING") -> None:
        self.machine = Machine(model=self, states=self.states, initial=initial_state)

        self.machine.add_transition("on_zone_touched", "SCANNING", "MONITORING")
        self.machine.add_transition("on_confirmation", "MONITORING", "IN_TRADE")
        self.machine.add_transition("on_invalidation", "MONITORING", "INVALID")
        self.machine.add_transition("on_expiry", "IN_TRADE", "EXPIRED")
        self.machine.add_transition("on_expiry", "MONITORING", "EXPIRED")
        self.machine.add_transition("reset_scan", "INVALID", "SCANNING")
        self.machine.add_transition("reset_scan", "EXPIRED", "SCANNING")
