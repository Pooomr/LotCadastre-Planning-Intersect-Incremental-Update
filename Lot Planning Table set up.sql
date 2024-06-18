--LOT_ZONE TABLE
--DROP TABLE MTRAN.LOT_ZONE CASCADE CONSTRAINTS;

CREATE TABLE MTRAN.LOT_ZONE
(
  LOT_ZONE_ID  INTEGER                          NOT NULL,
  LOTREF       VARCHAR2(260 BYTE),
  EPI_NAME     VARCHAR2(260 BYTE),
  EPI_TYPE     VARCHAR2(260 BYTE),
  SYM_CODE     VARCHAR2(20 BYTE)                NOT NULL,
  LAY_CLASS    VARCHAR2(260 BYTE),
  SUM_AREA     NUMBER,
  PERCENTAGE   NUMBER,
  CREATE_DATE  DATE                             DEFAULT CURRENT_TIMESTAMP,
  UPDATE_DATE  DATE                             DEFAULT CURRENT_TIMESTAMP,
  END_DATE     DATE                             DEFAULT null
)
TABLESPACE USERS
PCTUSED    0
PCTFREE    10
INITRANS   1
MAXTRANS   255
STORAGE    (
            INITIAL          1M
            NEXT             1M
            MINEXTENTS       1
            MAXEXTENTS       UNLIMITED
            PCTINCREASE      0
            BUFFER_POOL      DEFAULT
           )
LOGGING 
NOCOMPRESS 
NOCACHE
MONITORING;


GRANT SELECT ON MTRAN.LOT_ZONE TO KKINNAVONG;

GRANT SELECT ON MTRAN.LOT_ZONE TO PMACK;

--lot_zone_update_log
CREATE TABLE LZ_UPDATE_LOG
(
    LZ_UPDATE_LOG_ID        INTEGER     NOT NULL,
    START_DATE              DATE,
    END_DATE                DATE,
    CREATE_DATE             DATE,
    FINISH_DATE             DATE,
    TOTAL_RECORDS           INTEGER,
    RUN_USER                VARCHAR2(20 BYTE)
);

ALTER TABLE LZ_UPDATE_LOG ADD (
CONSTRAINT LZ_UPDATE_LOG_PK
  PRIMARY KEY
  (LZ_UPDATE_LOG_ID));

CREATE SEQUENCE SEQ_LZ_UPDATE_LOG  MINVALUE 1 MAXVALUE 1000000000 INCREMENT BY 1 START WITH 1 CACHE 20 NOORDER  NOCYCLE;

--Lots to extract spatial
CREATE TABLE LZ_LOT_SPATIAL
(
    LZ_LOT_SPATIAL_ID       INTEGER     NOT NULL,
    LZ_UPDATE_LOG_ID        INTEGER     NOT NULL,
    LOTREF                  VARCHAR(260 BYTE),
    CREATE_DATE             DATE,
    PROCESSED               DATE
);

ALTER TABLE LZ_LOT_SPATIAL ADD (
CONSTRAINT LZ_LOT_SPATIAL_PK
  PRIMARY KEY
  (LZ_LOT_SPATIAL_ID),
CONSTRAINT LZ_LOT_LOG_FK
    FOREIGN KEY (LZ_UPDATE_LOG_ID)
    REFERENCES LZ_UPDATE_LOG (LZ_UPDATE_LOG_ID));

--Zone BBOXs to extract Lots
CREATE TABLE LZ_ZONE_BBOX
(
    LZ_ZONE_BBOX_ID         INTEGER     NOT NULL,
    LZ_UPDATE_LOG_ID        INTEGER     NOT NULL,
    LZ_ZONE_OID             INTEGER     NOT NULL,
    LZ_ZONE_INFO            VARCHAR2(250),
    SPATIAL_REF             VARCHAR2(10),
    BBOX                    VARCHAR2(4000),
    PROCESSED               DATE
);

ALTER TABLE LZ_ZONE_BBOX ADD (
CONSTRAINT LZ_ZONE_BBOX_PK
    PRIMARY KEY
    (LZ_ZONE_BBOX_ID),
CONSTRAINT LZ_BBOX_LOG_FK
    FOREIGN KEY (LZ_UPDATE_LOG_ID)
    REFERENCES LZ_UPDATE_LOG (LZ_UPDATE_LOG_ID));
