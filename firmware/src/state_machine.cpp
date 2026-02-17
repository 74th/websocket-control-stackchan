#include <M5Unified.h>
#include "state_machine.hpp"

void StateMachine::setState(State s)
{
	log_i("State change: %u -> %u", static_cast<unsigned>(state_), static_cast<unsigned>(s));
	state_ = s;
}

StateMachine::State StateMachine::getState() const
{
	return state_;
}

bool StateMachine::isIdle() const
{
	return state_ == Idle;
}

bool StateMachine::isStreaming() const
{
	return state_ == Streaming;
}
