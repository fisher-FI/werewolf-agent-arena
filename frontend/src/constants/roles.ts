// 全角色元数据（与后端 Role 枚举对齐）
export const ROLE_EMOJI: Record<string, string> = {
  werewolf: '🐺', alpha_wolf: '👑', white_wolf_king: '💀',
  seer: '🔮', witch: '🧪', hunter: '🔫', guard: '🛡️',
  idiot: '🤡', knight: '⚔️', cupid: '💘', villager: '👤',
};

export const ROLE_LABEL: Record<string, string> = {
  werewolf: '狼人', alpha_wolf: '狼王', white_wolf_king: '白狼王',
  seer: '预言家', witch: '女巫', hunter: '猎人', guard: '守卫',
  idiot: '白痴', knight: '骑士', cupid: '丘比特', villager: '平民',
};

export const TEAM_LABEL: Record<string, string> = {
  werewolf: '狼人阵营', villager: '好人阵营', lovers: '情侣阵营',
};

export const getTeam = (role: string | null | undefined): string =>
  ['werewolf', 'alpha_wolf', 'white_wolf_king'].includes(role ?? '')
    ? 'werewolf'
    : 'villager';
