#include <M5Unified.h>
#include "state_machine.hpp"

namespace
{
const char *stateToString(StateMachine::State s)
{
	switch (s)
	{
	case StateMachine::Idle:
		return "Idle";
	case StateMachine::Streaming:
		return "Streaming";
	default:
		return "Unknown";
	}
}
}

void StateMachine::setState(State s)
{
	if (state_ == s)
	{
		return;
	}

	log_i("State change: %s -> %s", stateToString(state_), stateToString(s));

	State prev = state_;
	for (auto &cb : exit_events_[static_cast<size_t>(prev)])
	{
		cb(prev, s);
	}
	state_ = s;
	for (auto &cb : entry_events_[static_cast<size_t>(state_)])
	{
		cb(prev, state_);
	}
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

void StateMachine::addStateEntryEvent(State state, Callback cb)
{
	entry_events_[static_cast<size_t>(state)].push_back(std::move(cb));
}

void StateMachine::addStateExitEvent(State state, Callback cb)
{
	exit_events_[static_cast<size_t>(state)].push_back(std::move(cb));
}
