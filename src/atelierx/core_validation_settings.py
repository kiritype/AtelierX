"""Core SQLite persistence for revisioned Validation settings; never secrets."""
from __future__ import annotations
import copy, json, re, sqlite3, time
from .common import ApiError, canonical
from .validation_registry import GROUP_PROFILE_FIELDS, OPTIONAL_PROVIDER_FIELDS, PROFILE_FIELDS, PROVIDER_FIELDS, public_provider

IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
def invalid(message): raise ApiError("CORE_VALIDATION_SETTINGS_INVALID", message, 422)

def profile(value):
    if not isinstance(value, dict) or set(value) != PROFILE_FIELDS: invalid("Invalid single-image validation profile")
    if not isinstance(value["profile_id"], str) or not IDENT.fullmatch(value["profile_id"]): invalid("Invalid profile_id")
    if type(value["revision"]) is not int or value["revision"] < 1: invalid("Invalid profile revision")
    if not isinstance(value["body_parts"], list) or value["body_parts"] or value["metadata"] or value["consistency"]: invalid("Profile enables checks unavailable in the single-image adapter")
    if any(type(value[k]) is not bool for k in ("output_conditions","positive_prompt","negative_prompt","metadata","consistency")): invalid("Profile flags must be boolean")
    if not any(value[k] for k in ("output_conditions","positive_prompt","negative_prompt")): invalid("Profile must enable a supported check")
    return copy.deepcopy(value)

def provider(value):
    allowed = PROVIDER_FIELDS | OPTIONAL_PROVIDER_FIELDS | {"url","response_format","image_format","shared_gpu","api_key_env"}
    if not isinstance(value,dict) or not PROVIDER_FIELDS <= set(value) or set(value)-allowed: invalid("Invalid validation provider")
    if not isinstance(value["provider_id"],str) or not IDENT.fullmatch(value["provider_id"]): invalid("Invalid provider_id")
    if type(value["revision"]) is not int or value["revision"] < 1 or not isinstance(value["model"],str) or not value["model"] or type(value["timeout_seconds"]) is not int or value["timeout_seconds"] < 1: invalid("Invalid provider fields")
    if "max_tokens" in value and (type(value["max_tokens"]) is not int or value["max_tokens"] < 1): invalid("Invalid provider max_tokens")
    if not isinstance(value.get("url"),str) or not value["url"].startswith(("http://","https://")): invalid("Provider url must be http(s)")
    if "api_key" in value: invalid("Provider secrets cannot be stored in Core")
    if "api_key_env" in value and (not isinstance(value["api_key_env"],str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*",value["api_key_env"])): invalid("Invalid api_key_env")
    return copy.deepcopy(value)

def group_profile(value):
    fields = GROUP_PROFILE_FIELDS
    if not isinstance(value, dict) or set(value) != fields or value.get("consistency") is not True: invalid("Invalid group consistency profile")
    if not isinstance(value["profile_id"], str) or not IDENT.fullmatch(value["profile_id"]): invalid("Invalid profile_id")
    if type(value["revision"]) is not int or value["revision"] < 1: invalid("Invalid profile revision")
    return copy.deepcopy(value)

class ValidationSettings:
    KINDS={"profile","group_profile","provider"}
    def __init__(self, db:sqlite3.Connection, legacy=None):
        self.db=db; db.executescript("CREATE TABLE IF NOT EXISTS validation_settings (id TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL,archived INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,kind)); CREATE TABLE IF NOT EXISTS validation_setting_revisions (id TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,kind,revision));")
        for kind,entries in (("profile",(legacy or {}).get("profiles",{})),("group_profile",(legacy or {}).get("group_profiles",{})),("provider",(legacy or {}).get("providers",{}))):
            for raw in entries.values():
                # Older JSON used one `profiles` map.  A consistency-only entry
                # belongs to the group namespace, not the single adapter.
                actual_kind = "group_profile" if kind == "profile" and isinstance(raw, dict) and set(raw) == GROUP_PROFILE_FIELDS else kind
                try: self.seed(actual_kind,raw)
                except ApiError: pass
    @staticmethod
    def _id(kind): return "provider_id" if kind=="provider" else "profile_id"
    @classmethod
    def _validate(cls,kind,value):
        if kind not in cls.KINDS: invalid("Unknown validation setting kind")
        return profile(value) if kind=="profile" else group_profile(value) if kind=="group_profile" else provider(value)
    @staticmethod
    def _public(doc): return {k:v for k,v in doc.items() if k not in {"created_at","updated_at","api_key_env"}}
    def seed(self,kind,raw):
        doc=self._validate(kind,raw); ident=doc[self._id(kind)]
        if kind in {"profile","group_profile"} and self.db.execute("SELECT 1 FROM validation_settings WHERE id=? AND kind IN ('profile','group_profile')",(ident,)).fetchone(): return None
        if self.db.execute("SELECT 1 FROM validation_settings WHERE id=? AND kind=?",(ident,kind)).fetchone(): return None
        now=time.time(); stored=dict(doc,kind=kind,archived=False,created_at=now,updated_at=now)
        with self.db:
            self.db.execute("INSERT INTO validation_settings VALUES(?,?,?,?,?)",(ident,kind,doc["revision"],0,canonical(stored)))
            self.db.execute("INSERT INTO validation_setting_revisions VALUES(?,?,?,?)",(ident,kind,doc["revision"],canonical(stored)))
        return self._public(stored)
    def current(self,kind,ident):
        if kind not in self.KINDS: invalid("Unknown validation setting kind")
        if not isinstance(ident,str) or not IDENT.fullmatch(ident): invalid("Invalid validation setting id")
        row=self.db.execute("SELECT document FROM validation_settings WHERE id=? AND kind=?",(ident,kind)).fetchone()
        if not row: raise ApiError("CORE_VALIDATION_SELECTION_UNKNOWN","Unknown validation profile or provider",400)
        return json.loads(row[0])
    def list(self,kind,include_archived=False):
        if kind not in self.KINDS: invalid("Unknown validation setting kind")
        return [self._public(json.loads(r[0])) for r in self.db.execute("SELECT document FROM validation_settings WHERE kind=? AND (? OR archived=0) ORDER BY id",(kind,int(include_archived)))]
    def history(self,kind,ident):
        self.current(kind,ident)
        return [self._public(json.loads(r[0])) for r in self.db.execute("SELECT document FROM validation_setting_revisions WHERE id=? AND kind=? ORDER BY revision DESC",(ident,kind))]
    def create(self,kind,value):
        doc=self._validate(kind,value); ident=doc[self._id(kind)]
        if self.db.execute("SELECT 1 FROM validation_settings WHERE id=? AND kind=?",(ident,kind)).fetchone(): raise ApiError("CORE_VALIDATION_SETTINGS_CONFLICT","Setting already exists",409)
        if kind in {"profile","group_profile"} and self.db.execute("SELECT 1 FROM validation_settings WHERE id=? AND kind IN ('profile','group_profile')",(ident,)).fetchone(): raise ApiError("CORE_VALIDATION_SETTINGS_CONFLICT","Profile id is already used by another profile kind",409)
        return self.seed(kind,doc)
    def update(self,kind,ident,revision,value,archived=None):
        if type(revision) is not int or revision < 1: invalid("Invalid validation setting revision")
        if not isinstance(value,dict): invalid("Validation setting must be an object")
        if archived is not None and type(archived) is not bool: invalid("archived must be boolean")
        current=self.current(kind,ident)
        if current["revision"]!=revision: raise ApiError("CORE_REVISION_CONFLICT","Validation setting changed; refresh",409)
        doc=self._validate(kind,dict(value,**{self._id(kind):ident,"revision":revision+1}))
        stored=dict(doc,kind=kind,archived=current["archived"] if archived is None else bool(archived),created_at=current["created_at"],updated_at=time.time())
        with self.db:
            result=self.db.execute("UPDATE validation_settings SET revision=?,archived=?,document=? WHERE id=? AND kind=? AND revision=?",(revision+1,int(stored["archived"]),canonical(stored),ident,kind,revision))
            if result.rowcount!=1: raise ApiError("CORE_REVISION_CONFLICT","Validation setting changed; refresh",409)
            self.db.execute("INSERT INTO validation_setting_revisions VALUES(?,?,?,?)",(ident,kind,revision+1,canonical(stored)))
        return self._public(stored)
    def clone(self,kind,ident,new_id):
        if not isinstance(new_id,str) or not IDENT.fullmatch(new_id): invalid("Invalid clone id")
        current=self.current(kind,ident); permitted=PROFILE_FIELDS if kind=="profile" else GROUP_PROFILE_FIELDS if kind=="group_profile" else PROVIDER_FIELDS|OPTIONAL_PROVIDER_FIELDS|{"url","response_format","image_format","shared_gpu","api_key_env"}
        value={k:v for k,v in current.items() if k in permitted}; value[self._id(kind)]=new_id; value["revision"]=1
        return self.create(kind,value)
    def archive(self,kind,ident,revision):
        current=self.current(kind,ident)
        allowed=PROFILE_FIELDS if kind=="profile" else GROUP_PROFILE_FIELDS if kind=="group_profile" else PROVIDER_FIELDS|OPTIONAL_PROVIDER_FIELDS|{"url","response_format","image_format","shared_gpu","api_key_env"}
        return self.update(kind,ident,revision,{k:v for k,v in current.items() if k in allowed},archived=True)
    def freeze(self,selection,profile_kind="profile",legacy_provider=None):
        if not isinstance(selection,dict) or set(selection)!={"profile_id","provider_id"}: invalid("Select profile_id and provider_id")
        if profile_kind not in {"profile","group_profile"}: invalid("Unknown validation profile kind")
        p=self.current(profile_kind,selection["profile_id"])
        # A registered provider always wins, including its archived rejection.
        # Legacy compact configuration is only a migration bridge when no
        # provider record exists at all.
        try: q=self.current("provider",selection["provider_id"])
        except ApiError as exc:
            if exc.code != "CORE_VALIDATION_SELECTION_UNKNOWN" or not isinstance(legacy_provider,dict): raise
            q=legacy_provider
        if p["archived"] or q.get("archived",False): raise ApiError("CORE_VALIDATION_SELECTION_ARCHIVED","Profile or provider is archived",409)
        fields=PROFILE_FIELDS if profile_kind == "profile" else GROUP_PROFILE_FIELDS
        try: public=public_provider(q)
        except KeyError: raise ApiError("CORE_VALIDATION_SELECTION_UNKNOWN","Unknown validation provider",400) from None
        return {"selection":copy.deepcopy(selection),"profile":{k:p[k] for k in fields},"provider":public}
    def freeze_group(self,selection,legacy_provider=None): return self.freeze(selection,"group_profile",legacy_provider)
    def registry(self):
        docs=[json.loads(r[0]) for r in self.db.execute("SELECT document FROM validation_setting_revisions ORDER BY kind,id,revision")]
        return {"profiles":[{k:d[k] for k in (PROFILE_FIELDS if d["kind"]=="profile" else GROUP_PROFILE_FIELDS)} for d in docs if d["kind"] in {"profile","group_profile"}],"providers":[{k:d[k] for k in d if k in PROVIDER_FIELDS|OPTIONAL_PROVIDER_FIELDS|{"url","response_format","image_format","shared_gpu"}} for d in docs if d["kind"]=="provider"]}
