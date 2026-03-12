from app.core.enums import LeadStage


TERMINAL_STAGES = {LeadStage.BOOKED}


class LeadStagePolicy:
    @staticmethod
    def resolve(current: LeadStage, proposed: LeadStage) -> LeadStage:
        # Keep terminal states stable to prevent accidental regression.
        if current in TERMINAL_STAGES:
            return current
        return proposed
