

def load_music_learner(data, config, load_path=None):
    learn = music_model_learner(data, config)
    return learn

def music_model_learner(data:DataBunch, config:dict=None, drop_mult:float=1.,
                        load_path:PathOrStr=None, **learn_kwargs) -> 'LanguageLearner':
    "Create a `Learner` with a language model from `data` and `arch`."
    _model_meta[MusicTransformerXL] = _model_meta[TransformerXL]
    model = get_language_model(MusicTransformerXL, len(data.vocab.itos), config=config, drop_mult=drop_mult)
    
    meta = _model_meta[TransformerXL]
    learn = MusicLearner(data, model, split_func=meta['split_lm'], **learn_kwargs)

    if load_path:
        state = torch.load(load_path, map_location='cpu')
        get_model(model).load_state_dict(state['model'], strict=False)
    return learn

class MusicTransformerXL(TransformerXL):
    def __init__(self, *args, **kwargs):
        import inspect
        sig = inspect.signature(TransformerXL)
        arg_params = { k:kwargs[k] for k in sig.parameters if k in kwargs }
        super().__init__(*args, **arg_params)
        
    def forward(self, x):
        #The hidden state has to be initiliazed in the forward pass for nn.DataParallel
        if self.mem_len > 0 and not self.init: 
            self.reset()
            self.init = True
        bs,x_len = x.size()
        inp = self.drop_emb(self.encoder(x)) #.mul_(self.d_model ** 0.5)
        m_len = self.hidden[0].size(1) if hasattr(self, 'hidden') and len(self.hidden[0].size()) > 1 else 0
        seq_len = m_len + x_len
        
        mask = rand_window_mask(x_len, m_len, inp.device, is_eval=not self.training) if self.mask else None
        if m_len == 0: mask[...,0,0] = 0
        #[None,:,:None] for einsum implementation of attention
        hids = []
        pos = torch.arange(seq_len-1, -1, -1, device=inp.device, dtype=inp.dtype)
        pos_enc = self.pos_enc(pos)
        hids.append(inp)
        for i, layer in enumerate(self.layers):
            mem = self.hidden[i] if self.mem_len > 0 else None
            inp = layer(inp, r=pos_enc, u=self.u, v=self.v, mask=mask, mem=mem)
            hids.append(inp)
        core_out = inp[:,-x_len:]
        if self.mem_len > 0 : self._update_mems(hids)
        return (self.hidden if self.mem_len > 0 else [core_out]),[core_out]