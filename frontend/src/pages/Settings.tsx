import { useState, useEffect } from 'react';
import { api } from '../services/api';
import './Settings.css';

interface AIConfigForm {
  provider: string;
  model: string;
  api_key: string;
  base_url: string;
  temperature: number;
  personality: string;
  max_tokens: number;
}

const PRESETS: Record<string, Partial<AIConfigForm>> = {
  xiaomi: {
    provider: 'xiaomi',
    model: 'mimo-v2.5-pro',
    base_url: 'https://token-plan-cn.xiaomimimo.com/v1',
    personality: '一个聪明、善于推理的玩家',
  },
  openai: {
    provider: 'openai',
    model: 'gpt-4o',
    base_url: 'https://api.openai.com/v1',
    personality: '一个冷静理性的玩家，善于分析逻辑漏洞',
  },
  anthropic: {
    provider: 'anthropic',
    model: 'claude-sonnet-4-20250514',
    base_url: 'https://api.anthropic.com/v1',
    personality: '一个善于共情和观察细节的玩家',
  },
  deepseek: {
    provider: 'deepseek',
    model: 'deepseek-chat',
    base_url: 'https://api.deepseek.com/v1',
    personality: '一个极其严谨的玩家，每一步都有详细推理',
  },
  gemini: {
    provider: 'google',
    model: 'gemini-2.5-pro',
    base_url: 'https://generativelanguage.googleapis.com/v1beta',
    personality: '一个激进冒险的玩家，喜欢大胆操作',
  },
  ollama: {
    provider: 'ollama',
    model: 'llama3.1',
    base_url: 'http://localhost:11434/v1',
    personality: '一个直觉型玩家',
  },
};

export default function Settings() {
  const [config, setConfig] = useState<AIConfigForm>({
    provider: 'xiaomi',
    model: 'mimo-v2.5-pro',
    api_key: '',
    base_url: '',
    temperature: 0.8,
    personality: '一个聪明、善于推理的玩家',
    max_tokens: 500,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getDefaultAI().then(data => {
      setConfig(prev => ({ ...prev, ...data, api_key: '' }));
    }).catch(e => setError(e.message));
  }, []);

  const applyPreset = (key: string) => {
    const preset = PRESETS[key];
    if (preset) {
      setConfig(prev => ({ ...prev, ...preset, api_key: prev.api_key }));
    }
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setSaved(false);
    try {
      await api.updateDefaultAI(config);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: any) {
      setError(e.message);
    }
    setSaving(false);
  };

  return (
    <div className="settings-page">
      <h2 className="page-title">⚙️ AI 模型设置</h2>

      <div className="settings-layout">
        {/* 快速预设 */}
        <div className="card settings-presets">
          <h3>快速预设</h3>
          <p className="settings-hint">选择一个预设快速填入模型参数，API Key 需手动填写</p>
          <div className="preset-grid">
            {Object.entries(PRESETS).map(([key, preset]) => (
              <button
                key={key}
                className={`preset-btn ${config.provider === key ? 'active' : ''}`}
                onClick={() => applyPreset(key)}
              >
                <span className="preset-name">{key}</span>
                <span className="preset-model">{preset.model}</span>
              </button>
            ))}
          </div>
        </div>

        {/* 配置表单 */}
        <div className="card settings-form">
          <div className="form-row">
            <div className="form-group">
              <label>模型提供商</label>
              <input
                value={config.provider}
                onChange={e => setConfig(prev => ({ ...prev, provider: e.target.value }))}
                placeholder="xiaomi / openai / anthropic ..."
              />
            </div>
            <div className="form-group">
              <label>模型名称</label>
              <input
                value={config.model}
                onChange={e => setConfig(prev => ({ ...prev, model: e.target.value }))}
                placeholder="mimo-v2.5-pro / gpt-4o ..."
              />
            </div>
          </div>

          <div className="form-group">
            <label>API 地址</label>
            <input
              value={config.base_url}
              onChange={e => setConfig(prev => ({ ...prev, base_url: e.target.value }))}
              placeholder="https://api.openai.com/v1"
            />
            <span className="form-hint">支持 OpenAI 兼容接口，会自动拼接完整路径</span>
          </div>

          <div className="form-group">
            <label>API 密钥</label>
            <input
              type="password"
              value={config.api_key}
              onChange={e => setConfig(prev => ({ ...prev, api_key: e.target.value }))}
              placeholder="留空则不更新"
            />
            <span className="form-hint">留空表示不修改已保存的密钥</span>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>温度 ({config.temperature})</label>
              <input
                type="range"
                min="0" max="1.5" step="0.1"
                value={config.temperature}
                onChange={e => setConfig(prev => ({ ...prev, temperature: parseFloat(e.target.value) }))}
              />
              <div className="range-labels">
                <span>保守</span><span>创意</span>
              </div>
            </div>
            <div className="form-group">
              <label>最大输出长度</label>
              <input
                type="number"
                value={config.max_tokens}
                onChange={e => setConfig(prev => ({ ...prev, max_tokens: parseInt(e.target.value) || 500 }))}
              />
            </div>
          </div>

          <div className="form-group">
            <label>人设 Prompt</label>
            <textarea
              rows={3}
              value={config.personality}
              onChange={e => setConfig(prev => ({ ...prev, personality: e.target.value }))}
              placeholder="描述 AI 玩家的性格特征..."
            />
            <span className="form-hint">所有 AI 玩家共用此人设，可在对局中自定义覆盖</span>
          </div>

          {error && <div className="form-error">{error}</div>}
          {saved && <div className="form-success">✓ 设置已保存</div>}

          <div className="form-actions">
            <button className="btn-primary" onClick={save} disabled={saving}>
              {saving ? '保存中...' : '保存设置'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
