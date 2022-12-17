# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pickle
from typing import List, Optional

import redis

from streamlit.runtime.app_session import AppSession
from streamlit.runtime.metrics_util import Installation
from streamlit.runtime.session_data import SessionData
from streamlit.runtime.session_manager import SessionInfo, SessionStorage
from streamlit.watcher import LocalSourcesWatcher


class RedisSessionStorage(SessionStorage):
    def __init__(self) -> None:
        self._redis_client = redis.Redis(host="localhost", port=6379, db=0)

        self._uploaded_file_manager = None
        self._message_enqueued_callback = None

    # NOTE: Terrible hack that should never make it anywhere near code merged into
    # develop.
    def set_uploaded_file_manager(self, uploaded_file_manager) -> None:
        self._uploaded_file_manager = uploaded_file_manager

    # NOTE: Terrible hack that should never make it anywhere near code merged into
    # develop.
    def set_message_enqueued_callback(self, message_enqueued_callback) -> None:
        self._message_enqueued_callback = message_enqueued_callback

    def _session_redis_key(self, session_id: str) -> str:
        installation_id = Installation.instance().installation_id_v3
        return f"session_info-{installation_id}-{session_id}"

    def _serialize_session(self, session_info: SessionInfo) -> bytes:
        session = session_info.session
        session_data = session._session_data

        return pickle.dumps(
            {
                "session_id": session.id,
                "main_script_path": session_data.main_script_path,
                "command_line": session_data.command_line,
                "script_run_count": session_info.script_run_count,
                "user_info": session._user_info,
                "user_session_state": session._session_state.filtered_state,
            }
        )

    def _deserialize_session(self, b: bytes) -> SessionInfo:
        deserialized_data = pickle.loads(b)

        session_data = SessionData(
            main_script_path=deserialized_data["main_script_path"],
            command_line=deserialized_data["command_line"],
        )

        assert self._uploaded_file_manager is not None
        assert self._message_enqueued_callback is not None

        session = AppSession(
            session_data=session_data,
            uploaded_file_manager=self._uploaded_file_manager,
            message_enqueued_callback=self._message_enqueued_callback,
            local_sources_watcher=LocalSourcesWatcher(session_data.main_script_path),
            user_info=deserialized_data["user_info"],
        )

        # NOTE: Two hacks that should never make it anywhere near code merged into
        # develop
        #   1) Change the newly created session's ID to the old one.
        #   2) Restore the session state of our newly created session to what was
        #      serialized.
        session.id = deserialized_data["session_id"]
        session_state = session._session_state
        for k, v in deserialized_data["user_session_state"].items():
            session_state[k] = v

        script_run_count = deserialized_data["script_run_count"]

        return SessionInfo(
            client=None,
            session=session,
            script_run_count=script_run_count,
        )

    def get(self, session_id: str) -> Optional[SessionInfo]:
        serialized_session = self._redis_client.get(self._session_redis_key(session_id))
        if serialized_session is None:
            return None

        return self._deserialize_session(serialized_session)

    def save(self, session_info: SessionInfo) -> None:
        session_id = session_info.session.id
        return self._redis_client.set(
            self._session_redis_key(session_id),
            self._serialize_session(session_info),
            ex=60 * 60,  # 1 hour
        )

    def delete(self, session_id: str) -> None:
        self._redis_client.delete(self._session_redis_key(session_id))

    # NOTE: Can get away with not implementing this for the prototype since it's not
    # currently used by the Runtime.
    def list(self) -> List[SessionInfo]:
        return []
